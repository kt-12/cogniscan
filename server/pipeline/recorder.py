"""Turn screencast frames (JPEG + timestamp) into a constant-frame-rate MP4.

The extension streams `Page.startScreencast` frames, which arrive only when the page repaints.
TRIBE reads the video as a wall-clock timeline (1 row per second), so we resample to a fixed
`fps` grid and hold the last frame across gaps. Frame k covers [k/fps, (k+1)/fps).

Run directory layout:
    frames/000001.jpg ...     raw frames
    frames.jsonl              {"file": "000001.jpg", "t": 1.234}   t = seconds since run start
    stimulus.mp4              output
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def load_frames(run_dir: Path) -> list[tuple[float, Path]]:
    index = run_dir / "frames.jsonl"
    if not index.exists():
        return []
    frames = []
    for line in index.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        p = run_dir / "frames" / rec["file"]
        if p.exists():
            frames.append((float(rec["t"]), p))
    frames.sort(key=lambda x: x[0])
    return frames


def resample(frames: list[tuple[float, Path]], fps: int, duration: float) -> list[Path]:
    """Pick one frame per slot on a fixed grid; hold the previous frame when none is newer."""
    if not frames:
        return []
    n = max(1, int(round(duration * fps)))
    out: list[Path] = []
    j = 0
    current = frames[0][1]
    for k in range(n):
        t = k / fps
        while j < len(frames) and frames[j][0] <= t + 1e-9:
            current = frames[j][1]
            j += 1
        out.append(current)
    return out


def build_video(
    run_dir: Path,
    *,
    fps: int = 10,
    duration: float | None = None,
    max_height: int = 720,
    max_width: int = 1280,
    out_name: str = "stimulus.mp4",
) -> dict:
    run_dir = Path(run_dir).resolve()
    frames = load_frames(run_dir)
    if not frames:
        raise RuntimeError(f"no frames recorded in {run_dir}")
    if duration is None:
        duration = frames[-1][0] + 1.0 / fps
    duration = max(duration, 1.0)
    slots = resample(frames, fps, duration)
    concat = run_dir / "frames_concat.txt"
    lines = []
    for p in slots:
        lines.append(f"file '{p.as_posix()}'")
        lines.append(f"duration {1 / fps:.6f}")
    lines.append(f"file '{slots[-1].as_posix()}'")  # concat demuxer needs a trailing entry
    concat.write_text("\n".join(lines) + "\n")
    out = run_dir / out_name
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        # frames can change size mid-run (viewport changes); fit them all onto one even-sized canvas
        "-vf", f"scale={max_width}:{max_height}:force_original_aspect_ratio=decrease,"
               f"pad={max_width}:{max_height}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p",
        "-r", str(fps), "-vsync", "cfr",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-an", "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    return {
        "video": str(out),
        "fps": fps,
        "duration_s": round(len(slots) / fps, 3),
        "n_source_frames": len(frames),
        "n_output_frames": len(slots),
    }


def probe(path: Path) -> dict:
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
        "fps": video.get("avg_frame_rate"),
    }
