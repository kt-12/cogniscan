"""Drive Chrome over the DevTools protocol without the extension (same server API, same loop).

Used for headless demos and tests: `scanmyweb agent URL --goal "..." [--headless]`.
Launches a fresh Chrome profile with --remote-debugging-port, injects extension/smw_core.js into
every document, streams Page.startScreencast frames to the server, asks /api/agent/step for the next
action, executes it with Input.* events (virtual mouse), and posts step events.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import httpx
import websocket

ROOT = Path(__file__).resolve().parent.parent
CORE_JS = (ROOT / "extension" / "smw_core.js").read_text()
KEYS = {"Enter": (13, "\r"), "Escape": (27, None), "Tab": (9, None), "Backspace": (8, None), "ArrowDown": (40, None), "ArrowUp": (38, None)}


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, suppress_origin=True, max_size=None)
        self.ws.settimeout(0.2)
        self.next_id = 0
        self.pending: dict[int, dict] = {}
        self.events: list[tuple[str, dict]] = []
        self.ignore: set[int] = set()
        self.on_event = None
        self.lock = threading.Lock()
        self.alive = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        while self.alive:
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:  # noqa: BLE001
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if "id" in msg:
                if msg["id"] in self.ignore:
                    self.ignore.discard(msg["id"])
                else:
                    self.pending[msg["id"]] = msg
            elif self.on_event:
                try:
                    self.on_event(msg["method"], msg.get("params", {}))
                except Exception as e:  # noqa: BLE001
                    print("event handler error", e, file=sys.stderr)

    def send_nowait(self, method: str, params: dict | None = None) -> None:
        """Fire-and-forget (safe to call from the reader thread, which must never block on a reply)."""
        with self.lock:
            self.next_id += 1
            mid = self.next_id
            self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        self.ignore.add(mid)

    def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        with self.lock:
            self.next_id += 1
            mid = self.next_id
            self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        t0 = time.time()
        while mid not in self.pending:
            if time.time() - t0 > timeout:
                raise TimeoutError(method)
            time.sleep(0.005)
        msg = self.pending.pop(mid)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    def close(self):
        self.alive = False
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def launch_chrome(url: str, headless: bool, chrome: str | None, port: int = 9333) -> tuple[subprocess.Popen, str]:
    binary = chrome or shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not binary:
        raise RuntimeError("no Chrome binary found; pass --chrome")
    profile = tempfile.mkdtemp(prefix="scanmyweb-chrome-")
    cmd = [
        binary, f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run",
        "--no-default-browser-check", "--window-size=1280,800", "--disable-infobars", "--hide-scrollbars",
        "--disable-features=TranslateUI", "--no-sandbox", "--mute-audio",
    ]
    if headless:
        cmd.append("--headless=new")
    cmd.append("about:blank")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
            page = next(t for t in targets if t["type"] == "page")
            return proc, page["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("Chrome did not expose a page target")


def drive(*, url: str, mode: str, goal: str, headless: bool, nav_model: str | None, interp_model: str | None,
          server: str, chrome: str | None, wait: bool = True) -> str:
    sys.stdout.reconfigure(line_buffering=True)
    http = httpx.Client(base_url=server, timeout=600)
    health = http.get("/api/health").json()
    if not health["llm"]["ok"]:
        raise SystemExit("LLM not ready: " + health["llm"]["detail"])
    max_s, max_steps = health["max_flow_seconds"], health["max_steps"]
    run = http.post("/api/runs", json={"url": url, "mode": mode, "goal": goal, "nav_model": nav_model, "interp_model": interp_model}).raise_for_status().json()
    run_id = run["id"]
    print(f"run {run_id}: {mode} {url} {goal!r}")

    proc, ws_url = launch_chrome(url, headless, chrome)
    cdp = CDP(ws_url)
    frames: list[dict] = []
    load_flag = threading.Event()
    t0 = [0.0]
    paused = [0.0, None]  # [total paused seconds, pause start]; the clock stops while the model thinks
    now = lambda: time.time() - t0[0] - paused[0]  # noqa: E731

    def on_event(method, params):
        if method == "Page.screencastFrame":
            if paused[1] is None:
                frames.append({"t": round(now(), 3), "data": params["data"]})
            try:
                cdp.send_nowait("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            except Exception:  # noqa: BLE001
                pass
        elif method in ("Page.loadEventFired", "Page.frameStoppedLoading"):
            load_flag.set()

    cdp.on_event = on_event

    def flush():
        if frames:
            batch = frames[:]
            del frames[: len(batch)]
            http.post(f"/api/runs/{run_id}/frames", json={"frames": batch}).raise_for_status()

    def ev(expr):
        r = cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return r.get("result", {}).get("value")

    def ensure_core():
        if not ev("!!window.__smw"):
            cdp.send("Runtime.evaluate", {"expression": CORE_JS})

    mouse = [640, 400]

    def move(x, y, steps=10):
        for i in range(1, steps + 1):
            px = mouse[0] + (x - mouse[0]) * i / steps
            py = mouse[1] + (y - mouse[1]) * i / steps
            ev(f"window.__smw && window.__smw.cursor({px},{py},false)")
            cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": px, "y": py})
            time.sleep(0.035)
        mouse[0], mouse[1] = x, y

    def click(x, y):
        move(x, y)
        time.sleep(0.12)
        ev(f"window.__smw && window.__smw.cursor({x},{y},true)")
        cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        time.sleep(0.07)
        cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})

    def key(name):
        vk, text = KEYS.get(name, KEYS["Enter"])
        cdp.send("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": name, "code": name, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})
        if text:
            cdp.send("Input.dispatchKeyEvent", {"type": "char", "text": text, "key": name, "code": name, "windowsVirtualKeyCode": vk})
        cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": name, "code": name, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})

    def execute(action):
        bb = (action.get("element") or {}).get("bbox") or {}
        t = action["type"]
        if t == "click":
            click(bb["x"], bb["y"])
        elif t == "type":
            click(bb["x"], bb["y"])
            ev(f"window.__smw && window.__smw.focus({action['id']})")
            cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2, "windowsVirtualKeyCode": 65})
            cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2, "windowsVirtualKeyCode": 65})
            for ch in action.get("text", ""):
                cdp.send("Input.insertText", {"text": ch})
                time.sleep(0.045)
            if action.get("submit"):
                time.sleep(0.2)
                key("Enter")
        elif t == "scroll":
            move(640, 400, 6)
            dy = -220 if action.get("direction") == "up" else 220
            for _ in range(3):
                cdp.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": mouse[0], "y": mouse[1], "deltaX": 0, "deltaY": dy})
                time.sleep(0.14)
        elif t == "key":
            key(action.get("key", "Enter"))
        elif t == "navigate":
            load_flag.clear()
            cdp.send("Page.navigate", {"url": action["url"]})
            load_flag.wait(6)
        elif t == "wait":
            time.sleep(action.get("ms", 1500) / 1000)

    history: list[dict] = []
    reason = "done"
    try:
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": CORE_JS})
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False})
        load_flag.clear()
        cdp.send("Page.navigate", {"url": url})
        load_flag.wait(15)
        t0[0] = time.time()
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": 1280, "maxHeight": 800, "everyNthFrame": 1})
        time.sleep(3.0)
        step = 0
        while True:
            flush()
            elapsed = now()
            if elapsed > max_s - 4:
                reason = "time cap reached"
                break
            if step >= max_steps:
                reason = "step cap reached"
                break
            ensure_core()
            marked = ev("JSON.stringify(window.__smw.mark())")
            marked = json.loads(marked) if marked else {"elements": [], "viewport": {"url": url, "title": ""}}
            time.sleep(0.08)
            before = cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70})["data"]
            ev("window.__smw && window.__smw.unmark()")
            t_start = now()
            paused[1] = time.time()
            res = http.post("/api/agent/step", json={
                "run_id": run_id, "url": marked["viewport"]["url"], "title": marked["viewport"]["title"],
                "elements": marked["elements"], "history": history, "screenshot": before, "step_index": step, "elapsed_s": now(),
            }).raise_for_status().json()
            paused[0] += time.time() - paused[1]
            paused[1] = None
            action = res["action"]
            print(f"  step {step + 1} @{elapsed:5.1f}s: {action['type']} {action.get('id', '')} {action.get('text', '')!r:.30} — {action.get('label')} | {action.get('reason', '')[:90]}")
            act = {k: v for k, v in action.items() if k != "element"}

            def post(i, a, b, shot_before, shot_after):
                try:
                    cur = ev("JSON.stringify({url: location.href, title: document.title})") or "{}"
                    cur = json.loads(cur)
                except Exception:  # noqa: BLE001
                    cur = marked["viewport"]
                http.post(f"/api/runs/{run_id}/steps", json={
                    "i": i, "t0": round(a, 3), "t1": round(b, 3), "action": act, "element": action.get("element"),
                    "url": cur.get("url", ""), "title": cur.get("title", ""), "label": action.get("label", ""),
                    "screenshot_before": shot_before, "screenshot_after": shot_after,
                }).raise_for_status()

            if action["type"] == "done":
                reason = action.get("reason", "done")
                post(step, t_start, now() + 1.5, before, None)
                break
            ts = now()
            url_before = marked["viewport"]["url"]
            load_flag.clear()
            try:
                execute(action)
            except Exception as e:  # noqa: BLE001
                print("  execute failed:", e)
            time.sleep(1.0)
            cur_url = ev("location.href") or url_before
            if cur_url != url_before:
                load_flag.wait(5)
                time.sleep(0.3)
                ensure_core()
            time.sleep(2.5)  # dwell so TRIBE sees the result of the action
            try:
                after = cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70})["data"]
            except Exception:  # noqa: BLE001
                after = None
            te = now()
            post(step, ts, te, before, after)
            history.append({"i": step, "action": {"type": action["type"], "id": action.get("id"), "text": action.get("text")}, "label": action.get("label"), "url": cur_url})
            step += 1
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        time.sleep(2.0)  # final dwell
        duration = min(now() + 0.5, max_s)
        try:
            cdp.send("Page.stopScreencast")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
        flush()
        cdp.close()
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    http.post(f"/api/runs/{run_id}/finish", json={"duration_s": duration, "reason": reason}).raise_for_status()
    print(f"recorded {duration:.1f}s ({reason}); processing queued")
    if wait:
        last = ""
        while True:
            r = http.get(f"/api/runs/{run_id}").json()
            p = r.get("progress", {})
            line = f"  {r['status']}: {p.get('stage', '')} {p.get('pct', 0):.0f}%"
            if line != last:
                print(line)
                last = line
            if r["status"] in ("done", "failed"):
                break
            time.sleep(3)
        if r["status"] == "failed":
            raise SystemExit("processing failed: " + str(r.get("error")))
        print(f"done -> {server}/view/{run_id}")
    return run_id
