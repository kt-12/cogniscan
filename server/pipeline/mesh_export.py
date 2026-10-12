#!/usr/bin/env python
"""Export the inflated fsaverage5 mesh + HCP parcel ids for the browser viewer.

    python -m server.pipeline.mesh_export OUT_JSON

Executed with the TRIBE interpreter (needs nilearn + mne). Output JSON fields (typed arrays are
base64 of little-endian binary):
    nV, nHemi, nFaces, hemiCenters
    coords   Float32 nV x 3 (mm; x right, y anterior, z up), hemispheres side by side
    faces    Uint32  nFaces x 3
    sulc     Float32 nV, sulcal depth (positive = sulcus)
    parcel   Uint16  nV, 0 = none, else 1-based index into parcelNames
    parcelNames  ["L_V1", ..., "R_V1", ...]
    roiGroups    {key: {label, parcels, hemi, about, parcelIds: [...]}}
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

N_HEMI = 10242
HEMI_GAP = 12.0


def b64(arr) -> str:
    import numpy as np

    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode("ascii")


def main(out: Path) -> None:
    import numpy as np
    from hcp import ROI_GROUPS, load_parcels
    from nilearn import datasets, surface

    fs = datasets.fetch_surf_fsaverage("fsaverage5")
    coords, faces, sulc, centers = [], [], [], []
    for h, hemi in enumerate(("left", "right")):
        mesh = surface.load_surf_mesh(fs[f"infl_{hemi}"])
        xyz = np.asarray(mesh.coordinates, dtype=np.float64)
        assert xyz.shape == (N_HEMI, 3), xyz.shape
        xyz = xyz - (xyz.max(0) + xyz.min(0)) / 2
        half_width = (xyz[:, 0].max() - xyz[:, 0].min()) / 2
        shift = (half_width + HEMI_GAP / 2) * (-1 if hemi == "left" else 1)
        xyz[:, 0] += shift
        centers.append([round(float(shift), 3), 0.0, 0.0])
        coords.append(xyz)
        faces.append(np.asarray(mesh.faces, dtype=np.uint32) + h * N_HEMI)
        sulc.append(np.asarray(surface.load_surf_data(fs[f"sulc_{hemi}"]), dtype=np.float32))
    coords = np.vstack(coords).astype(np.float32)
    faces = np.vstack(faces).astype(np.uint32)
    sulc = np.concatenate(sulc)

    by_name, names = load_parcels()
    parcel_names: list[str] = []
    parcel = np.zeros(2 * N_HEMI, dtype=np.uint16)
    for (name, hemi), idx in sorted(by_name.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        key = f"{'L' if hemi == 'left' else 'R'}_{name}"
        parcel_names.append(key)
        parcel[idx] = len(parcel_names)
    roi_groups = {}
    for k, spec in ROI_GROUPS.items():
        hemis = ["left", "right"] if spec["hemi"] == "both" else [spec["hemi"]]
        ids = []
        for p in spec["parcels"]:
            for h in hemis:
                key = f"{'L' if h == 'left' else 'R'}_{p}"
                if key in parcel_names:
                    ids.append(parcel_names.index(key) + 1)
        roi_groups[k] = {**spec, "parcelIds": ids}

    payload = {
        "surface": "fsaverage5 inflated (nilearn), hemispheres centred and placed side by side",
        "nV": int(coords.shape[0]),
        "nHemi": N_HEMI,
        "nFaces": int(faces.shape[0]),
        "hemiCenters": centers,
        "coords": b64(coords),
        "faces": b64(faces),
        "sulc": b64(sulc),
        "parcel": b64(parcel),
        "parcelNames": parcel_names,
        "roiGroups": roi_groups,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"{out}: {coords.shape[0]} vertices, {faces.shape[0]} faces, {len(parcel_names)} parcels, "
          f"{out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).resolve())
