"""Background processing of a recorded run: video → TRIBE worker → stats → interpretation → slides.json.

One worker thread processes runs sequentially (the GPU is shared with the Ollama models).
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
import traceback
from pathlib import Path

from ..config import CONFIG, ROOT
from ..interpret.stats import load_tribe, run_stats
from ..interpret.writer import interpret_run, interpret_step
from .recorder import build_video

WORKER = ROOT / "server" / "pipeline" / "tribe_worker.py"
_ENCODING_RE = re.compile(r"Encoding video:\s*(\d+)%")


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def write_json(p: Path, data) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(p)


class RunStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
            raise ValueError("bad run id")
        return self.data_dir / run_id

    def get(self, run_id: str) -> dict | None:
        return read_json(self.dir(run_id) / "run.json")

    def save(self, run: dict) -> None:
        write_json(self.dir(run["id"]) / "run.json", run)

    def update(self, run_id: str, **fields) -> dict:
        run = self.get(run_id) or {"id": run_id}
        run.update(fields)
        run["updated"] = time.time()
        self.save(run)
        return run

    def list(self) -> list[dict]:
        runs = []
        for p in sorted(self.data_dir.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            r = read_json(p)
            if r:
                runs.append(r)
        return runs


class JobQueue:
    def __init__(self, store: RunStore):
        self.store = store
        self.q: queue.Queue[str] = queue.Queue()
        self.current: str | None = None
        self.thread = threading.Thread(target=self._loop, daemon=True, name="scanmyweb-jobs")
        self.thread.start()

    def submit(self, run_id: str) -> None:
        self.store.update(run_id, status="queued", progress={"stage": "queued", "pct": 0})
        self.q.put(run_id)

    def pending(self) -> list[str]:
        return list(self.q.queue)

    def _loop(self) -> None:
        while True:
            run_id = self.q.get()
            self.current = run_id
            try:
                process_run(self.store, run_id)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.store.update(
                    run_id, status="failed", error=f"{type(e).__name__}: {e}",
                    progress={"stage": "failed", "pct": 0},
                )
            finally:
                self.current = None
                self.q.task_done()


def _set_progress(store: RunStore, run_id: str, stage: str, pct: float, **extra) -> None:
    store.update(run_id, status="processing", progress={"stage": stage, "pct": round(pct, 1), **extra})


def run_tribe_worker(store: RunStore, run_id: str, video: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "worker.log"
    cmd = [
        str(CONFIG.tribe_python), str(WORKER), str(video), str(out_dir),
        "--cache", str(CONFIG.tribe_cache),
        "--checkpoint", CONFIG.tribe_checkpoint,
        "--max-height", str(CONFIG.video_max_height),
    ]
    if not CONFIG.tribe_python.exists():
        raise RuntimeError(f"TRIBE interpreter not found: {CONFIG.tribe_python} (set SCANMYWEB_TRIBE_PYTHON)")
    with open(log, "w") as lf:
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), env=CONFIG.worker_env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        assert proc.stdout is not None
        buf = ""
        last_pct = 5.0
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                break
            lf.write(ch)
            if ch in "\r\n":
                line = buf
                buf = ""
                m = _ENCODING_RE.search(line)
                if m:
                    # feature extraction is ~90% of the time: map 0-100% of encoding to 8-90%
                    pct = 8 + 0.82 * int(m.group(1))
                    if pct - last_pct >= 1:
                        last_pct = pct
                        _set_progress(store, run_id, "TRIBE: encoding video", pct)
                elif line.startswith("[worker]"):
                    pj = read_json(out_dir / "progress.json", {})
                    if pj:
                        _set_progress(store, run_id, "TRIBE: " + pj.get("stage", ""), max(last_pct, pj.get("pct", 0)))
            else:
                buf += ch
        proc.wait()
    if proc.returncode != 0:
        tail = "".join(log.read_text().splitlines(keepends=True)[-15:])
        raise RuntimeError(f"TRIBE worker exited with {proc.returncode}:\n{tail}")


def process_run(store: RunStore, run_id: str) -> dict:
    run_dir = store.dir(run_id)
    run = store.get(run_id) or {}
    steps = read_json(run_dir / "steps.json", []) or []
    t_start = time.time()

    # 1. video
    video = run_dir / "stimulus.mp4"
    if not video.exists():
        _set_progress(store, run_id, "building video", 2)
        info = build_video(
            run_dir, fps=CONFIG.video_fps, duration=run.get("duration_s"),
            max_height=CONFIG.video_max_height,
        )
        store.update(run_id, video=info)

    # 2. TRIBE
    tribe_dir = run_dir / "tribe"
    if not (tribe_dir / "tribe_meta.json").exists():
        _set_progress(store, run_id, "TRIBE: loading model", 5)
        run_tribe_worker(store, run_id, video, tribe_dir)

    # 3. stats
    _set_progress(store, run_id, "summarising", 91)
    tribe = load_tribe(tribe_dir)
    n_rows = tribe["preds"].shape[0]
    if not steps:  # no step events (CLI run): one step per 5 s
        steps = [
            {"i": k, "t0": float(k * 5), "t1": float(min(n_rows, k * 5 + 5)), "action": {"type": "wait"},
             "label": f"{k * 5}-{min(n_rows, k * 5 + 5)} s", "url": run.get("url", ""), "title": ""}
            for k in range((n_rows + 4) // 5)
        ]
    rstats = run_stats(tribe, steps)

    # 4. interpretation
    run = store.get(run_id) or run
    model = run.get("interp_model") or CONFIG.interp_model
    slides = []
    existing = read_json(run_dir / "slides.json", {}) or {}
    cached = {s["i"]: s for s in existing.get("slides", [])} if existing.get("interp_model") == model else {}
    for k, (step, st) in enumerate(zip(steps, rstats["steps"], strict=False)):
        _set_progress(store, run_id, f"interpreting step {k + 1}/{len(steps)}", 91 + 8 * k / max(1, len(steps)))
        if step["i"] in cached and cached[step["i"]].get("interp", {}).get("interpretation") and "error" not in cached[step["i"]]["interp"]:
            interp = cached[step["i"]]["interp"]
        else:
            shot = None
            for name in (step.get("screenshot_after"), step.get("screenshot_before")):
                if name and (run_dir / "steps" / name).exists():
                    shot = (run_dir / "steps" / name).read_bytes()
                    break
            interp = interpret_step(step, st, run, model=model, image=shot)
        slides.append({**step, "stats": st, "interp": interp})
    summary = interpret_run(run, steps, rstats["steps"], rstats, model=model)

    meta = tribe["meta"]
    out = {
        "run": {k: v for k, v in run.items() if k not in ("progress",)},
        "interp_model": model,
        "tribe": {
            "model": meta["model"],
            "license": meta["license"],
            "modalities": meta["modalities"],
            "TR_s": meta["TR_s"],
            "n_seconds": n_rows,
            "i8_scale": meta["i8_scale"],
            "caveats": meta["caveats"],
            "runtime": meta["runtime"],
            "per_second_mean_abs": meta["global"]["per_second_mean_abs"],
        },
        "roi_groups": tribe["parcels"].get("roi_groups", {}),
        "roi_means": tribe["parcels"].get("roi_means", {}),
        "run_stats": {k: v for k, v in rstats.items() if k != "steps"},
        "summary": summary,
        "slides": slides,
    }
    write_json(run_dir / "slides.json", out)
    store.update(
        run_id, status="done", progress={"stage": "done", "pct": 100},
        processing_s=round(time.time() - t_start, 1), n_slides=len(slides), interp_model=model,
        error=None,
    )
    return out
