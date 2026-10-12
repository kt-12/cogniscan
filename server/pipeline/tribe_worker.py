#!/usr/bin/env python
"""Run TRIBE v2 on one video. Executed with the TRIBE interpreter (`CONFIG.tribe_python`).

    python -m server.pipeline.tribe_worker VIDEO OUT_DIR --cache CACHE_DIR [--max-height 720]

Writes to OUT_DIR:
    preds.npy          float32 (n_seconds, 20484): predicted BOLD on fsaverage5, left then right
    preds.i8           int8 quantised copy for the viewer (value = int8 * scale / 127)
    segments.json      one entry per row: stimulus window, event types in the window
    parcels.json       per-second mean per HCP-MMP1 parcel (both hemispheres) + ROI group means
    tribe_meta.json    model / modality / timing facts the interpreter must know
    progress.json      {"stage": ..., "pct": ...} updated while running

Modalities: the released checkpoint uses video (V-JEPA2), audio (Wav2Vec-BERT) and text
(LLaMA 3.2, gated on Hugging Face). We build events with `get_audio_and_text_events(audio_only=True)`
so there are no Word events and the text extractor is dropped; the audio extractor is dropped too
when the video has no audio track. Missing modalities are fed as zeros, which is what modality
dropout did during training. Rows are already compensated for the 5 s hemodynamic lag.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # hcp.py, importable without the server package

HEMODYNAMIC_OFFSET_S = 5.0
N_VERTICES = 20484
I8_SCALE = 0.6  # predicted BOLD (a.u.) mapped to int8 127; 99.5th pct of |pred| on a reference run


def progress(out_dir: Path, stage: str, pct: float, **extra) -> None:
    (out_dir / "progress.json").write_text(
        json.dumps({"stage": stage, "pct": round(float(pct), 1), "t": time.time(), **extra})
    )
    print(f"[worker] {stage} {pct:.0f}%", flush=True)


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    info = json.loads(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {
        "duration_s": float(info["format"]["duration"]),
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
        "width": int(video["width"]),
        "height": int(video["height"]),
    }


def prepare_video(src: Path, out_dir: Path, max_height: int) -> tuple[Path, dict]:
    """Working copy named by a content hash: the neuralset feature cache is keyed by path."""
    h = hashlib.sha256(f"{max_height}|".encode())
    with open(src, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    dst = out_dir / "input" / f"stimulus_{h.hexdigest()[:12]}.mp4"
    info = ffprobe(src)
    if dst.exists():
        return dst, {"source": info, "working_copy": ffprobe(dst), "reused": True}
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0:v:0"]
    if info["has_audio"]:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    cmd += [
        "-vf", f"scale=-2:'min({max_height},ih)'",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(dst),
    ]
    subprocess.run(cmd, check=True)
    return dst, {"source": info, "working_copy": ffprobe(dst), "reused": False}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--cache", type=Path, required=True, help="neuralset feature cache folder")
    ap.add_argument("--checkpoint", default="facebook/tribev2")
    ap.add_argument("--max-height", type=int, default=720)
    ap.add_argument("--no-parcels", action="store_true")
    args = ap.parse_args()

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    src = args.video.resolve()
    if not src.is_file():
        sys.exit(f"video not found: {src}")
    t_start = time.time()
    progress(out_dir, "preparing video", 0)
    work_video, prep = prepare_video(src, out_dir, args.max_height)

    import numpy as np
    import pandas as pd
    import torch
    from tribev2.demo_utils import TribeModel, get_audio_and_text_events

    progress(out_dir, "loading model", 2)
    t0 = time.time()
    model = TribeModel.from_pretrained(
        args.checkpoint,
        cache_folder=args.cache,
        config_update={"data.num_workers": 0},
    )
    offset = float(model.data.neuro.offset)
    assert offset == HEMODYNAMIC_OFFSET_S, f"checkpoint offset is {offset}, expected 5"
    t_load = time.time() - t0

    events = pd.DataFrame([{
        "type": "Video", "filepath": str(work_video), "start": 0,
        "timeline": "default", "subject": "default",
    }])
    events = get_audio_and_text_events(events, audio_only=True)
    event_types = sorted(events.type.unique().tolist())

    progress(out_dir, "extracting features + predicting", 5)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    preds, segments = model.predict(events=events)
    t_predict = time.time() - t0
    preds = preds.astype(np.float32)
    assert preds.shape[1] == N_VERTICES, preds.shape
    np.save(out_dir / "preds.npy", preds)
    q = np.clip(np.rint(preds / I8_SCALE * 127), -127, 127).astype(np.int8)
    (out_dir / "preds.i8").write_bytes(np.ascontiguousarray(q).tobytes())

    tr = float(model.data.TR)
    work_dur = prep["working_copy"]["duration_s"]
    rows = []
    for i, seg in enumerate(segments):
        start = float(seg.start)
        rows.append({
            "i": i,
            "t0": round(start, 3),
            "t1": round(start + float(seg.duration), 3),
            "bold_time": round(start + offset, 3),
            "video_fraction": round(max(0.0, min(start + float(seg.duration), work_dur) - start) / tr, 3),
            "events": sorted({type(e).__name__ for e in seg.ns_events}),
        })
    (out_dir / "segments.json").write_text(json.dumps(rows))

    progress(out_dir, "summarising parcels", 92)
    parcels_out: dict = {"available": False}
    if not args.no_parcels:
        try:
            from hcp import ROI_GROUPS, load_parcels, roi_indices

            by_name, names = load_parcels()
            parcel_means = {}
            for (name, hemi), idx in by_name.items():
                parcel_means[f"{'L' if hemi == 'left' else 'R'}_{name}"] = (
                    preds[:, idx].mean(axis=1).round(5).tolist()
                )
            groups = roi_indices(by_name)
            roi_means = {k: preds[:, idx].mean(axis=1).round(5).tolist() for k, idx in groups.items() if idx}
            parcels_out = {
                "available": True,
                "atlas": "HCP-MMP1.0 (Glasser et al. 2016) on fsaverage via MNE, subsampled to fsaverage5",
                "parcel_names": names,
                "parcel_means": parcel_means,  # key "L_V1" -> list over seconds
                "roi_groups": {
                    k: {**{kk: vv for kk, vv in ROI_GROUPS[k].items()}, "n_vertices": len(groups[k])}
                    for k in roi_means
                },
                "roi_means": roi_means,  # key group -> list over seconds
            }
        except Exception as e:  # noqa: BLE001
            print(f"[worker] parcel summary failed: {e}", file=sys.stderr)
            parcels_out = {"available": False, "error": str(e)}
    (out_dir / "parcels.json").write_text(json.dumps(parcels_out))

    used = [m for m, t in [("video", "Video"), ("audio", "Audio"), ("text", "Word")] if t in event_types]
    meta = {
        "model": f"{args.checkpoint} (best.ckpt), average-subject predictions",
        "license": "CC-BY-NC-4.0 (non-commercial)",
        "video": str(src),
        "input_preparation": prep,
        "preds_shape": list(preds.shape),
        "preds_space": "fsaverage5, 10242 left-hemisphere vertices then 10242 right",
        "preds_units": "model output trained against normalised BOLD; arbitrary units, relative only",
        "i8_scale": I8_SCALE,
        "i8_clipped_fraction": round(float((np.abs(preds) > I8_SCALE).mean()), 5),
        "TR_s": tr,
        "hemodynamic_offset_s": offset,
        "modalities": {
            "trained_with": ["text", "audio", "video"],
            "used": used,
            "zeroed": [m for m in ["text", "audio", "video"] if m not in used],
        },
        "global": {
            "mean_abs": float(np.abs(preds).mean()),
            "p99_abs": float(np.percentile(np.abs(preds), 99)),
            "per_second_mean_abs": np.abs(preds).mean(axis=1).round(5).tolist(),
            "per_second_spatial_std": preds.std(axis=1).round(5).tolist(),
        },
        "runtime": {
            "model_load_s": round(t_load, 1),
            "features_and_predict_s": round(t_predict, 1),
            "total_s": round(time.time() - t_start, 1),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "gpu_peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)
            if torch.cuda.is_available() else None,
            "torch": torch.__version__,
        },
        "caveats": [
            "Predicted average-subject fMRI responses, not an engagement, attention, emotion or quality score.",
            "Only the video modality carries stimulus information in this pipeline (no audio track, LLaMA text extractor not loaded).",
            "BOLD is slow (response spread over ~10 s) and the model attends over a 100 s window: a row reflects several seconds of content around it.",
            "The first seconds contain a stimulus-onset transient.",
        ],
    }
    (out_dir / "tribe_meta.json").write_text(json.dumps(meta, indent=2))
    progress(out_dir, "done", 100)
    print(f"[worker] preds {preds.shape}; modalities {used}; total {meta['runtime']['total_s']} s")


if __name__ == "__main__":
    os.environ.setdefault("MPLBACKEND", "Agg")
    main()
