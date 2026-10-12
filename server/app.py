"""scanmyweb local server: run registry, recording ingest, agent step endpoint, slideshow."""

from __future__ import annotations

import base64
import json
import secrets
import shutil
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent.planner import next_action
from .config import CONFIG
from .llm import describe_models, get_provider, presets
from .pipeline.tribe_job import JobQueue, RunStore, read_json, write_json

app = FastAPI(title="scanmyweb", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
store = RunStore(CONFIG.data_dir)
jobs = JobQueue(store)


# ---------------------------------------------------------------- models / health
class RunCreate(BaseModel):
    url: str
    mode: str = "goal"  # goal | explore
    goal: str = ""
    nav_model: str | None = None
    interp_model: str | None = None


class FrameBatch(BaseModel):
    frames: list[dict]  # [{"t": seconds, "data": base64 jpeg}]


class StepIn(BaseModel):
    i: int
    t0: float
    t1: float
    action: dict
    url: str = ""
    title: str = ""
    label: str = ""
    element: dict | None = None
    screenshot_before: str | None = None  # base64 jpeg
    screenshot_after: str | None = None


class AgentStepIn(BaseModel):
    run_id: str
    url: str = ""
    title: str = ""
    elements: list[dict] = []
    history: list[dict] = []
    screenshot: str | None = None  # base64 jpeg
    step_index: int = 0
    elapsed_s: float = 0.0


class FinishIn(BaseModel):
    duration_s: float | None = None
    reason: str = ""


@app.get("/api/health")
def health():
    nav = get_provider(CONFIG.nav_model)
    ok, msg = nav.healthy()
    return {
        "ok": True,
        "nav_model": CONFIG.nav_model,
        "interp_model": CONFIG.interp_model,
        "llm": {"ok": ok, "detail": msg},
        "tribe_python": str(CONFIG.tribe_python),
        "tribe_python_ok": CONFIG.tribe_python.exists(),
        "mesh_ok": (CONFIG.static_dir / "mesh.json").exists(),
        "max_flow_seconds": CONFIG.max_flow_seconds,
        "max_steps": CONFIG.max_steps,
        "processing": jobs.current,
        "queued": jobs.pending(),
    }


@app.get("/api/models")
def models():
    return {"models": describe_models(), "nav_model": CONFIG.nav_model, "interp_model": CONFIG.interp_model}


# ---------------------------------------------------------------- runs
@app.get("/api/runs")
def list_runs():
    return {"runs": store.list(), "processing": jobs.current, "queued": jobs.pending()}


@app.post("/api/runs")
def create_run(body: RunCreate):
    if body.mode not in ("goal", "explore"):
        raise HTTPException(400, "mode must be goal or explore")
    for m in (body.nav_model, body.interp_model):
        if m and m not in presets():
            raise HTTPException(400, f"unknown model preset {m!r}")
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    d = store.dir(run_id)
    (d / "frames").mkdir(parents=True)
    (d / "steps").mkdir()
    run = {
        "id": run_id,
        "url": body.url,
        "mode": body.mode,
        "goal": body.goal,
        "nav_model": body.nav_model or CONFIG.nav_model,
        "interp_model": body.interp_model or CONFIG.interp_model,
        "status": "recording",
        "created": time.time(),
        "max_flow_seconds": CONFIG.max_flow_seconds,
        "max_steps": CONFIG.max_steps,
        "n_frames": 0,
        "n_steps": 0,
    }
    store.save(run)
    write_json(d / "steps.json", [])
    return run


def _run_or_404(run_id: str) -> dict:
    try:
        run = store.get(run_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not run:
        raise HTTPException(404, "run not found")
    return run


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    return _run_or_404(run_id)


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    _run_or_404(run_id)
    if jobs.current == run_id:
        raise HTTPException(409, "run is being processed")
    shutil.rmtree(store.dir(run_id))
    return {"deleted": run_id}


@app.post("/api/runs/{run_id}/frames")
def add_frames(run_id: str, body: FrameBatch):
    run = _run_or_404(run_id)
    if run["status"] != "recording":
        raise HTTPException(409, f"run is {run['status']}")
    d = store.dir(run_id)
    n = int(run.get("n_frames", 0))
    kept = 0
    with open(d / "frames.jsonl", "a") as idx:
        for fr in body.frames:
            t = float(fr["t"])
            if t > CONFIG.max_flow_seconds + 1:
                continue
            n += 1
            name = f"{n:06d}.jpg"
            (d / "frames" / name).write_bytes(base64.b64decode(fr["data"]))
            idx.write(json.dumps({"file": name, "t": round(t, 3)}) + "\n")
            kept += 1
    store.update(run_id, n_frames=n)
    return {"accepted": kept, "n_frames": n}


@app.post("/api/runs/{run_id}/steps")
def add_step(run_id: str, body: StepIn):
    run = _run_or_404(run_id)
    if run["status"] != "recording":
        raise HTTPException(409, f"run is {run['status']}")
    d = store.dir(run_id)
    steps = read_json(d / "steps.json", []) or []
    rec = body.model_dump()
    for key in ("screenshot_before", "screenshot_after"):
        b64 = rec.pop(key)
        if b64:
            name = f"step{body.i:03d}_{key.split('_')[1]}.jpg"
            (d / "steps" / name).write_bytes(base64.b64decode(b64))
            rec[key] = name
        else:
            rec[key] = None
    steps = [s for s in steps if s["i"] != body.i] + [rec]
    steps.sort(key=lambda s: s["i"])
    write_json(d / "steps.json", steps)
    store.update(run_id, n_steps=len(steps))
    return {"n_steps": len(steps)}


@app.post("/api/runs/{run_id}/finish")
def finish_run(run_id: str, body: FinishIn):
    run = _run_or_404(run_id)
    if run["status"] == "recording":
        dur = body.duration_s
        if dur is None:
            steps = read_json(store.dir(run_id) / "steps.json", []) or []
            dur = max([s["t1"] for s in steps] + [1.0])
        dur = float(min(dur, CONFIG.max_flow_seconds))
        store.update(run_id, status="recorded", duration_s=dur, finish_reason=body.reason)
    jobs.submit(run_id)
    return store.get(run_id)


@app.post("/api/runs/{run_id}/reprocess")
def reprocess(run_id: str, interp_model: str | None = None, redo_tribe: bool = False, redo_interp: bool = False):
    _run_or_404(run_id)
    d = store.dir(run_id)
    if redo_tribe:
        shutil.rmtree(d / "tribe", ignore_errors=True)
    if redo_tribe or redo_interp:
        (d / "slides.json").unlink(missing_ok=True)
    if interp_model:
        if interp_model not in presets():
            raise HTTPException(400, f"unknown model preset {interp_model!r}")
        store.update(run_id, interp_model=interp_model)
    jobs.submit(run_id)
    return store.get(run_id)


# ---------------------------------------------------------------- agent
@app.post("/api/agent/step")
def agent_step(body: AgentStepIn):
    run = _run_or_404(body.run_id)
    seconds_left = CONFIG.max_flow_seconds - body.elapsed_s
    shot = base64.b64decode(body.screenshot) if body.screenshot else None
    action = next_action(
        mode=run.get("mode", "goal"),
        goal=run.get("goal", ""),
        url=body.url,
        title=body.title,
        elements=body.elements,
        history=body.history,
        screenshot=shot,
        model=run.get("nav_model") or CONFIG.nav_model,
        step_index=body.step_index,
        max_steps=CONFIG.max_steps,
        seconds_left=seconds_left,
    )
    return {"action": action, "seconds_left": seconds_left}


# ---------------------------------------------------------------- run files
def _file(run_id: str, rel: str) -> Path:
    _run_or_404(run_id)
    p = (store.dir(run_id) / rel).resolve()
    if not str(p).startswith(str(store.dir(run_id).resolve())) or not p.exists():
        raise HTTPException(404, "file not found")
    return p


@app.get("/api/runs/{run_id}/slides.json")
def slides(run_id: str):
    return FileResponse(_file(run_id, "slides.json"), media_type="application/json")


@app.get("/api/runs/{run_id}/preds.i8")
def preds_i8(run_id: str):
    return Response(_file(run_id, "tribe/preds.i8").read_bytes(), media_type="application/octet-stream")


@app.get("/api/runs/{run_id}/video")
def video(run_id: str, request: Request):
    return FileResponse(_file(run_id, "stimulus.mp4"), media_type="video/mp4")


@app.get("/api/runs/{run_id}/steps/{name}")
def step_image(run_id: str, name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "bad name")
    return FileResponse(_file(run_id, f"steps/{name}"), media_type="image/jpeg")


@app.get("/api/runs/{run_id}/log")
def worker_log(run_id: str):
    p = store.dir(run_id) / "tribe" / "worker.log"
    _run_or_404(run_id)
    return Response(p.read_text()[-20000:] if p.exists() else "", media_type="text/plain")


# ---------------------------------------------------------------- UI
@app.get("/")
def index():
    return FileResponse(CONFIG.static_dir / "index.html")


@app.get("/view/{run_id}")
def view(run_id: str):
    _run_or_404(run_id)
    return FileResponse(CONFIG.static_dir / "index.html")


@app.get("/mesh.json")
def mesh():
    p = CONFIG.static_dir / "mesh.json"
    if not p.exists():
        return JSONResponse({"error": "mesh.json missing: run `scanmyweb export-mesh`"}, status_code=404)
    return FileResponse(p, media_type="application/json")


app.mount("/static", StaticFiles(directory=str(CONFIG.static_dir)), name="static")
