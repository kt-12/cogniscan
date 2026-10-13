#!/usr/bin/env python
"""Render a side-by-side MP4 of a run: website recording | predicted brain activity, with a caption strip.

    python video_export.py RUN_DIR SURF_DIR [--views lateral|four] [--fps 10] [--threshold T] [--range R]

Runs inside the TRIBE interpreter (pyvista + VTK off-screen, nibabel, Pillow). Output:
    RUN_DIR/export.mp4         3200 x (720|1440) + 110 px caption strip, h264 yuv420p, silent
                               (website 1280 wide | two 960-wide brain views; `four` adds a medial row)
    RUN_DIR/export_progress.json

Brain frames are rendered at the output frame rate; predictions (one row per second) are linearly
interpolated between rows so the animation is smooth. Colours match the web viewer: sulcal-depth
grey base, orange/yellow for positive, blue/cyan for negative, transparent below the threshold.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

N_HEMI = 10242
W_HALF = 1280  # website column
W_BRAIN = 960  # per brain view
H_ROW = 720
CAPTION_H = 110
BG = (21, 23, 28)
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF")

# ---------------------------------------------------------------- pure helpers (unit-tested in the server venv)


def frame_times(duration_s: float, fps: int) -> list[float]:
    """Timestamps of the output frames: 0, 1/fps, ... < duration."""
    n = int(round(duration_s * fps))
    return [i / fps for i in range(n)]


def interp_weights(t: float, n_rows: int) -> tuple[int, int, float]:
    """(row_a, row_b, w): value = (1-w)*row_a + w*row_b for time t (rows are 1 s apart, centred on the second)."""
    if n_rows <= 1:
        return 0, 0, 0.0
    x = min(max(t - 0.5, 0.0), n_rows - 1.0)
    a = int(x)
    b = min(a + 1, n_rows - 1)
    return a, b, x - a


def caption_for(t: float, slides: list[dict]) -> dict | None:
    """The slide whose window contains t (falls back to the latest slide that started before t)."""
    best = None
    for s in slides:
        st = s.get("stats", {})
        t0, t1 = float(st.get("t0", s.get("t0", 0))), float(st.get("t1", s.get("t1", 0)))
        if t0 <= t < t1:
            return s
        if t >= t0:
            best = s
    return best


def diverging_rgb(v, thr: float, rng: float, base):
    """Blend per-vertex values onto a grey base. v: (N,) float, base: (N,3) float 0-1 → uint8 (N,3)."""
    import numpy as np

    v = np.asarray(v, dtype=np.float32)
    a = np.clip((np.abs(v) - thr) / max(1e-6, rng - thr), 0.0, 1.0)[:, None]
    pos_lo, pos_hi = np.array([1.0, 0.48, 0.10]), np.array([1.0, 0.89, 0.42])
    neg_lo, neg_hi = np.array([0.15, 0.39, 0.92]), np.array([0.40, 0.91, 0.98])
    f = np.clip(np.abs(v) / max(1e-6, rng), 0, 1)[:, None]
    col = np.where((v >= 0)[:, None], pos_lo + (pos_hi - pos_lo) * f, neg_lo + (neg_hi - neg_lo) * f)
    out = base * (1 - a) + col * a
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


def sulc_base(sulc) -> object:
    """Grey base shading from sulcal depth (sulci darker), (N,3) float."""
    import numpy as np

    s = np.asarray(sulc, dtype=np.float32)
    lo, hi = np.percentile(s, 5), np.percentile(s, 95)
    g = 0.78 - 0.30 * np.clip((s - lo) / max(1e-6, hi - lo), 0, 1)
    return np.repeat(g[:, None], 3, axis=1)


# ---------------------------------------------------------------- rendering


def _font(size: int):
    from PIL import ImageFont

    for d in FONT_DIRS:
        for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
            p = Path(d) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def caption_strip(width: int, slide: dict | None, t: float, duration: float, run: dict, fonts) -> object:
    import numpy as np
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, CAPTION_H), BG)
    d = ImageDraw.Draw(img)
    big, small, mono = fonts
    if slide:
        i = slide.get("i", 0) + 1
        head = slide.get("interp", {}).get("headline") or slide.get("label") or ""
        action = slide.get("label") or ""
        d.text((24, 14), f"Step {i}  ·  {head}"[:110], fill=(255, 255, 255), font=big)
        line2 = f"{action}  ·  {slide.get('url', '')}"[:150]
        d.text((24, 52), line2, fill=(160, 168, 184), font=small)
    d.text((24, 80), f"{run.get('url', '')}   TRIBE v2 average-subject prediction, video only  ·  {t:5.1f} / {duration:.0f} s",
           fill=(120, 128, 144), font=mono)
    # progress bar
    x0, x1, y = 24, width - 24, CAPTION_H - 6
    d.rectangle([x0, y - 2, x1, y + 1], fill=(42, 47, 58))
    d.rectangle([x0, y - 2, x0 + (x1 - x0) * min(1.0, t / max(1e-6, duration)), y + 1], fill=(255, 122, 26))
    # legend (right side)
    lw = 160
    lx = width - 24 - lw
    for k in range(lw):
        f = k / (lw - 1)
        v = (f - 0.5) * 2
        c = diverging_rgb(np.array([v]), 0.08, 1.0, np.array([[0.3, 0.32, 0.37]]))[0]
        d.line([lx + k, 20, lx + k, 32], fill=tuple(int(x) for x in c))
    d.text((lx - 40, 18), "−", fill=(160, 168, 184), font=small)
    d.text((lx + lw + 8, 18), "+", fill=(160, 168, 184), font=small)
    d.text((lx, 38), "predicted BOLD vs run", fill=(120, 128, 144), font=mono)
    return np.asarray(img)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("surf_dir")
    ap.add_argument("--views", choices=["lateral", "four"], default="lateral")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--threshold", type=float, default=0.08)
    ap.add_argument("--range", dest="rng", type=float, default=0.6)
    ap.add_argument("--out", default="export.mp4")
    args = ap.parse_args()

    import nibabel as nib
    import numpy as np
    import pyvista as pv

    pv.OFF_SCREEN = True
    run_dir, surf_dir = Path(args.run_dir), Path(args.surf_dir)
    t_start = time.time()

    def progress(stage: str, pct: float, **extra) -> None:
        (run_dir / "export_progress.json").write_text(json.dumps({"stage": stage, "pct": round(pct, 1), **extra}))
        print(f"[export] {stage} {pct:.0f}%", flush=True)

    progress("loading", 1)
    preds = np.load(run_dir / "tribe" / "preds.npy").astype(np.float32)
    slides_doc = json.loads((run_dir / "slides.json").read_text())
    slides = slides_doc.get("slides", [])
    run = slides_doc.get("run", {})
    stimulus = run_dir / "stimulus.mp4"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(stimulus)], capture_output=True, text=True, check=True,
    )
    pj = json.loads(probe.stdout)
    duration = min(float(pj["format"]["duration"]), float(preds.shape[0]))
    times = frame_times(duration, args.fps)
    n_frames = len(times)

    # meshes
    hemis = []
    for h, name in enumerate(("lh", "rh")):
        g = nib.load(str(surf_dir / f"{name}.inflated.surf.gii"))
        coords = g.darrays[0].data.astype(np.float64)
        faces = g.darrays[1].data.astype(np.int64)
        sulc = nib.freesurfer.read_morph_data(str(surf_dir / f"{name}.sulc.curv"))
        fc = np.hstack([np.full((len(faces), 1), 3), faces]).ravel()
        mesh = pv.PolyData(coords, fc)
        mesh.point_data["rgb"] = np.full((coords.shape[0], 3), 128, dtype=np.uint8)
        hemis.append({"mesh": mesh, "base": sulc_base(sulc), "lo": h * N_HEMI})

    # plotter: one subplot per view; lateral = [lh lateral | rh lateral]; four adds medial row
    rows = 2 if args.views == "four" else 1
    H = H_ROW * rows
    p = pv.Plotter(off_screen=True, shape=(rows, 2), window_size=(2 * W_BRAIN, H), border=False)
    bg = "#{:02x}{:02x}{:02x}".format(*BG)
    views = [(0, 0, 0, "lateral"), (0, 1, 1, "lateral")]
    if rows == 2:
        views += [(1, 0, 0, "medial"), (1, 1, 1, "medial")]
    for r, c, h, kind in views:
        p.subplot(r, c)
        p.set_background(bg)
        p.add_mesh(hemis[h]["mesh"], scalars="rgb", rgb=True, smooth_shading=True, show_scalar_bar=False,
                   specular=0.15, specular_power=20, ambient=0.25, diffuse=0.8)
        # lh lateral = camera at -x; rh lateral = camera at +x; medial = the opposite side
        from_neg_x = (h == 0) == (kind == "lateral")
        p.view_yz(negative=from_neg_x)
        p.camera.up = (0, 0, 1)
        p.camera.zoom(1.55)
        p.add_text(f"{'left' if h == 0 else 'right'} {kind}", position="upper_left", font_size=11, color=(150, 158, 175))
    p.enable_anti_aliasing("fxaa")
    p.image_scale = 1  # some VTK builds default to a HiDPI scale; we need exactly 2*W_HALF x H

    fonts = (_font(26), _font(18), _font(15))
    out_w, out_h = W_HALF + 2 * W_BRAIN, H + CAPTION_H
    out_path = run_dir / args.out
    tmp_path = run_dir / (args.out + ".part.mp4")

    # input: decode the stimulus at the output fps, scaled/padded to 1280x720
    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(stimulus), "-vf",
         f"fps={args.fps},scale={W_HALF}:{H_ROW}:force_original_aspect_ratio=decrease,pad={W_HALF}:{H_ROW}:(ow-iw)/2:(oh-ih)/2:color=black",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"] if "h264_nvenc" in encoders else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}", "-r", str(args.fps),
         "-i", "-", *vcodec, "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp_path)],
        stdin=subprocess.PIPE,
    )
    assert dec.stdout is not None and enc.stdin is not None
    frame_bytes = W_HALF * H_ROW * 3
    last_pct = -1.0
    black = np.zeros((H_ROW, W_HALF, 3), dtype=np.uint8)
    for k, t in enumerate(times):
        raw = dec.stdout.read(frame_bytes)
        web = np.frombuffer(raw, dtype=np.uint8).reshape(H_ROW, W_HALF, 3) if len(raw) == frame_bytes else black
        a, b, w = interp_weights(t, preds.shape[0])
        row = preds[a] * (1 - w) + preds[b] * w
        for hm in hemis:
            v = row[hm["lo"]:hm["lo"] + N_HEMI]
            hm["mesh"].point_data["rgb"] = diverging_rgb(v, args.threshold, args.rng, hm["base"])
        brain = p.screenshot(return_img=True)[:, :, :3]
        if brain.shape[:2] != (H, 2 * W_BRAIN):
            from PIL import Image

            brain = np.asarray(Image.fromarray(brain).resize((2 * W_BRAIN, H), Image.BILINEAR))
        if rows == 1:
            left = web
        else:  # four views: website letterboxed in the middle of the taller left column
            left = np.zeros((H, W_HALF, 3), dtype=np.uint8)
            y0 = (H - H_ROW) // 2
            left[y0:y0 + H_ROW] = web
        top = np.concatenate([left, brain], axis=1)
        strip = caption_strip(out_w, caption_for(t, slides), t, duration, run, fonts)
        frame = np.concatenate([top, strip], axis=0)
        enc.stdin.write(np.ascontiguousarray(frame).tobytes())
        pct = 3 + 95 * (k + 1) / n_frames
        if pct - last_pct >= 2:
            last_pct = pct
            progress("rendering", pct, frame=k + 1, n_frames=n_frames)
    enc.stdin.close()
    dec.stdout.close()
    dec.wait()
    rc = enc.wait()
    if rc != 0:
        raise SystemExit(f"ffmpeg encoder exited with {rc}")
    tmp_path.replace(out_path)
    meta = {"file": out_path.name, "size": out_path.stat().st_size, "width": out_w, "height": out_h, "fps": args.fps,
            "n_frames": n_frames, "views": args.views, "render_s": round(time.time() - t_start, 1)}
    (run_dir / "export.json").write_text(json.dumps(meta, indent=1))
    progress("done", 100, **meta)


if __name__ == "__main__":
    sys.exit(main())
