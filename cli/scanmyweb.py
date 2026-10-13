"""scanmyweb command line.

    scanmyweb serve                       start the local server (http://127.0.0.1:8787)
    scanmyweb run VIDEO [--steps STEPS.json] [--url URL] [--goal TEXT]
                                          process an existing screen recording (no extension needed)
    scanmyweb agent URL [--goal TEXT | --explore] [--headless]
                                          drive Chrome over the DevTools protocol (no extension needed)
    scanmyweb export-mesh                 (re)build server/static/mesh.json with the TRIBE interpreter
    scanmyweb models                      list model presets and check the LLM backend
    scanmyweb runs                        list runs
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.config import CONFIG  # noqa: E402
from server.config import ROOT as SROOT


def cmd_serve(args) -> None:
    import uvicorn

    print(f"scanmyweb server on http://{CONFIG.host}:{CONFIG.port}  (nav={CONFIG.nav_model}, interp={CONFIG.interp_model})")
    print("Load the extension: chrome://extensions -> Developer mode -> Load unpacked -> ./extension")
    uvicorn.run("server.app:app", host=CONFIG.host, port=CONFIG.port, reload=args.reload, log_level="info")


def cmd_run(args) -> None:
    from server.pipeline.tribe_job import RunStore, process_run, write_json

    store = RunStore(CONFIG.data_dir)
    run_id = args.id or (time.strftime("%Y%m%d-%H%M%S") + "-cli")
    d = store.dir(run_id)
    (d / "steps").mkdir(parents=True, exist_ok=True)
    src = Path(args.video).resolve()
    if not src.is_file():
        sys.exit(f"video not found: {src}")
    shutil.copyfile(src, d / "stimulus.mp4")
    steps = json.loads(Path(args.steps).read_text()) if args.steps else []
    write_json(d / "steps.json", steps)
    store.save({
        "id": run_id, "url": args.url or src.name, "mode": "goal" if args.goal else "video",
        "goal": args.goal or f"screen recording {src.name}", "status": "recorded", "created": time.time(),
        "nav_model": CONFIG.nav_model, "interp_model": args.interp_model or CONFIG.interp_model,
        "n_steps": len(steps),
    })
    print(f"run {run_id}: processing {src} (this takes ~12x the video length on GPU)")
    out = process_run(store, run_id)
    print(f"done: {len(out['slides'])} slides -> http://{CONFIG.host}:{CONFIG.port}/view/{run_id}")


def cmd_agent(args) -> None:
    from cli.cdp_agent import drive

    drive(
        url=args.url, mode="explore" if args.explore else "goal", goal=args.goal or "",
        headless=args.headless, nav_model=args.nav_model, interp_model=args.interp_model,
        server=f"http://{CONFIG.host}:{CONFIG.port}", chrome=args.chrome, wait=not args.no_wait,
    )


def cmd_export_mesh(_args) -> None:
    out = SROOT / "server" / "static" / "surf"
    cmd = [str(CONFIG.tribe_python), str(SROOT / "server" / "pipeline" / "mesh_export.py"), str(out)]
    subprocess.run(cmd, check=True, env=CONFIG.worker_env())


def cmd_export_video(args) -> None:
    from server.pipeline.tribe_job import RunStore, run_export

    store = RunStore(CONFIG.data_dir)
    if not store.get(args.run):
        sys.exit(f"unknown run {args.run}")
    state = run_export(store, args.run, views=args.views, fps=args.fps)
    print(f"{store.dir(args.run) / state['file']}  {state['width']}x{state['height']} {state['fps']} fps, "
          f"{state['n_frames']} frames, {state['size'] / 1e6:.1f} MB, rendered in {state['render_s']} s")


def cmd_models(_args) -> None:
    from server.llm import describe_models, get_provider

    for m in describe_models():
        ok, msg = get_provider(m["name"]).healthy()
        flag = "ok " if ok else "-- "
        print(f"{flag} {m['name']:<18} {m['provider']:<13} {m['model']:<34} {'vision' if m['vision'] else '      '}  {m['description']}")
        if not ok:
            print(f"     {msg}")
    print(f"\nnav_model={CONFIG.nav_model}  interp_model={CONFIG.interp_model}")


def cmd_runs(args) -> None:
    from server.app import store
    from server.pipeline.tribe_job import backfill_surfaces

    for r in store.list():
        extra = ""
        if args.backfill and r.get("status") == "done":
            try:
                extra = "  func.gii: " + backfill_surfaces(store, r["id"])
            except Exception as e:  # noqa: BLE001
                extra = f"  func.gii FAILED: {e}"
        print(f"{r['id']:<24} {r.get('status', '?'):<11} {r.get('url', '')[:50]}{extra}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="scanmyweb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--reload", action="store_true"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("run"); s.add_argument("video"); s.add_argument("--steps"); s.add_argument("--url"); s.add_argument("--goal")
    s.add_argument("--id"); s.add_argument("--interp-model"); s.set_defaults(fn=cmd_run)
    s = sub.add_parser("agent"); s.add_argument("url"); s.add_argument("--goal"); s.add_argument("--explore", action="store_true")
    s.add_argument("--headless", action="store_true"); s.add_argument("--nav-model"); s.add_argument("--interp-model")
    s.add_argument("--chrome", default=None, help="chrome binary (default: google-chrome)"); s.add_argument("--no-wait", action="store_true", help="do not wait for processing")
    s.set_defaults(fn=cmd_agent)
    sub.add_parser("export-mesh").set_defaults(fn=cmd_export_mesh)
    s = sub.add_parser("export-video", help="render website | brain side-by-side MP4 for a processed run")
    s.add_argument("run"); s.add_argument("--views", choices=["lateral", "four"], default="lateral"); s.add_argument("--fps", type=int, default=10)
    s.set_defaults(fn=cmd_export_video)
    sub.add_parser("models").set_defaults(fn=cmd_models)
    s = sub.add_parser("runs"); s.add_argument("--backfill", action="store_true", help="write lh/rh.func.gii for done runs that lack them"); s.set_defaults(fn=cmd_runs)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
