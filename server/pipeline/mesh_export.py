#!/usr/bin/env python
"""Export the inflated fsaverage5 surfaces + HCP parcel ids for the browser viewer and the video export.

    python -m server.pipeline.mesh_export SURF_DIR

Executed with the TRIBE interpreter (needs nilearn + mne + nibabel). Writes to SURF_DIR:
    {lh,rh}.inflated.surf.gii   GIfTI surface (hemispheres centred, placed side by side; x right, y anterior, z up)
    {lh,rh}.sulc.curv           FreeSurfer curv, sulcal depth (positive = sulcus)
    parcels.json                {nHemi, parcelNames ["L_V1", ...], parcel: {lh: [...], rh: [...]} (0 = none,
                                else 1-based index into parcelNames), roiGroups: {key: {label, parcels, hemi,
                                about, parcelIds}}}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

N_HEMI = 10242
HEMI_GAP = 12.0


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

    # NiiVue-readable files: one GIfTI surface + curv per hemisphere, parcels as JSON
    from surfaces import HEMIS, write_curv, write_surf_gii

    surf_dir = out
    surf_dir.mkdir(parents=True, exist_ok=True)
    n_faces_hemi = faces.shape[0] // 2
    for h, hemi in enumerate(HEMIS):
        lo, hi = h * N_HEMI, (h + 1) * N_HEMI
        write_surf_gii(surf_dir / f"{hemi}.inflated.surf.gii", coords[lo:hi], faces[h * n_faces_hemi:(h + 1) * n_faces_hemi] - lo)
        write_curv(surf_dir / f"{hemi}.sulc.curv", sulc[lo:hi], n_faces_hemi)
    (surf_dir / "parcels.json").write_text(json.dumps({
        "nHemi": N_HEMI,
        "parcelNames": parcel_names,
        "parcel": {hemi: parcel[h * N_HEMI:(h + 1) * N_HEMI].tolist() for h, hemi in enumerate(HEMIS)},
        "roiGroups": roi_groups,
    }, separators=(",", ":")))
    print(f"{surf_dir}: " + ", ".join(sorted(q.name for q in surf_dir.iterdir())))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]).resolve())
