"""Deterministic summaries of TRIBE predictions per flow step: the "TRIBE says" strip.

Everything here is pure numpy over the worker outputs (`preds.npy`, `parcels.json`, `tribe_meta.json`);
no model calls. The LLM in `writer.py` only ever sees these numbers, never raw vertices.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

MIN_WINDOW_S = 2.0  # a click that lasts 0.4 s still gets a 2 s window of predictions


def load_tribe(tribe_dir: Path) -> dict:
    tribe_dir = Path(tribe_dir)
    preds = np.load(tribe_dir / "preds.npy")
    meta = json.loads((tribe_dir / "tribe_meta.json").read_text())
    parcels = json.loads((tribe_dir / "parcels.json").read_text())
    segments = json.loads((tribe_dir / "segments.json").read_text())
    return {"preds": preds, "meta": meta, "parcels": parcels, "segments": segments}


def window_rows(t0: float, t1: float, n_rows: int, tr: float = 1.0) -> list[int]:
    """Row indices whose 1 s window overlaps [t0, t1), widened to at least MIN_WINDOW_S."""
    if t1 - t0 < MIN_WINDOW_S:
        mid = (t0 + t1) / 2
        t0, t1 = mid - MIN_WINDOW_S / 2, mid + MIN_WINDOW_S / 2
    lo = max(0, int(np.floor(t0 / tr)))
    hi = min(n_rows, int(np.ceil(t1 / tr)))
    if hi <= lo:
        lo = min(max(0, lo), n_rows - 1)
        hi = lo + 1
    return list(range(lo, hi))


def _z(window_mean: float, series: np.ndarray) -> float:
    std = float(series.std())
    if std < 1e-6:
        return 0.0
    return float((window_mean - series.mean()) / std)


def step_stats(tribe: dict, t0: float, t1: float) -> dict:
    preds: np.ndarray = tribe["preds"]
    parcels = tribe["parcels"]
    meta = tribe["meta"]
    tr = float(meta.get("TR_s", 1.0))
    rows = window_rows(t0, t1, preds.shape[0], tr)
    win = preds[rows]
    per_sec_abs = np.abs(preds).mean(axis=1)

    out: dict = {
        "rows": rows,
        "t0": round(rows[0] * tr, 2),
        "t1": round((rows[-1] + 1) * tr, 2),
        "n_seconds": len(rows),
        "mean_abs": float(np.abs(win).mean()),
        "mean_abs_z": _z(float(np.abs(win).mean(axis=1).mean()), per_sec_abs),
        "spatial_std": float(win.std(axis=1).mean()),
        "peak_second": int(rows[int(np.argmax(per_sec_abs[rows]))]),
        "rois": [],
        "top_parcels": [],
        "bottom_parcels": [],
    }
    if not parcels.get("available"):
        out["sentence"] = "Parcel summary unavailable for this run."
        return out

    roi_rows = []
    for key, series in parcels["roi_means"].items():
        s = np.asarray(series, dtype=np.float32)
        wm = float(s[rows].mean())
        spec = parcels["roi_groups"][key]
        roi_rows.append({
            "key": key,
            "label": spec["label"],
            "about": spec.get("about", ""),
            "mean": wm,
            "z": _z(wm, s),
            "run_mean": float(s.mean()),
        })
    roi_rows.sort(key=lambda r: r["z"], reverse=True)
    out["rois"] = roi_rows

    pm = parcels["parcel_means"]
    names = list(pm.keys())
    mat = np.asarray([pm[n] for n in names], dtype=np.float32)  # n_parcels x nT
    wmean = mat[:, rows].mean(axis=1)
    zs = np.array([_z(float(wmean[i]), mat[i]) for i in range(len(names))])
    order = np.argsort(-wmean)
    out["top_parcels"] = [
        {"name": names[i], "mean": float(wmean[i]), "z": float(zs[i])} for i in order[:6]
    ]
    out["bottom_parcels"] = [
        {"name": names[i], "mean": float(wmean[i]), "z": float(zs[i])} for i in order[-4:][::-1]
    ]
    out["sentence"] = make_sentence(out)
    return out


def _fmt_z(z: float) -> str:
    return f"{z:+.1f}σ"


def make_sentence(st: dict) -> str:
    rois = st["rois"]
    up = [r for r in rois if r["z"] >= 0.5][:3]
    down = [r for r in rois if r["z"] <= -0.5][-2:]
    parts = []
    if up:
        parts.append(
            "Above this run's baseline: "
            + ", ".join(f"{r['label']} ({_fmt_z(r['z'])})" for r in up)
            + "."
        )
    if down:
        parts.append(
            "Below baseline: " + ", ".join(f"{r['label']} ({_fmt_z(r['z'])})" for r in down) + "."
        )
    if not up and not down:
        parts.append("All regions within ±0.5σ of this run's baseline.")
    if st["top_parcels"]:
        parts.append(
            "Strongest parcels: "
            + ", ".join(p["name"] for p in st["top_parcels"][:4])
            + "."
        )
    parts.append(
        f"Overall predicted activity {_fmt_z(st['mean_abs_z'])} vs run; peak at {st['peak_second']} s."
    )
    return " ".join(parts)


def run_stats(tribe: dict, steps: list[dict]) -> dict:
    """Run-level facts: which step has the strongest overall / per-ROI response."""
    per_step = [step_stats(tribe, s["t0"], s["t1"]) for s in steps]
    out = {"steps": per_step}
    if per_step:
        out["strongest_step"] = int(np.argmax([s["mean_abs"] for s in per_step]))
        out["weakest_step"] = int(np.argmin([s["mean_abs"] for s in per_step]))
        roi_keys = [r["key"] for r in per_step[0]["rois"]]
        out["roi_peaks"] = {}
        for k in roi_keys:
            vals = [next(r["mean"] for r in s["rois"] if r["key"] == k) for s in per_step]
            out["roi_peaks"][k] = int(np.argmax(vals))
    return out
