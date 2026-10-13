"""HCP-MMP1.0 (Glasser et al. 2016) parcels on fsaverage5, and the ROI groupings cogniscan reports.

Runs inside the TRIBE interpreter (needs `mne`). Same method as `tribev2.utils.get_hcp_labels`
and run_tribe.py: read the annotation on full fsaverage and keep vertices < 10242, which are the
fsaverage5 vertices. Left hemisphere vertices are 0..10241, right are 10242..20483, matching the
column order of TRIBE predictions.
"""

from __future__ import annotations

import os
from pathlib import Path

N_HEMI = 10242

# Groupings chosen for this project (bilateral unless `hemi` says otherwise). Parcel names are the
# HCP-MMP1.0 short names. Unknown names are skipped with a warning so a typo never breaks a run.
ROI_GROUPS: dict[str, dict] = {
    "early_visual": {
        "label": "Early visual (V1-V3)",
        "parcels": ["V1", "V2", "V3"],
        "hemi": "both",
        "about": "retinotopic cortex; responds to contrast, edges and visual change anywhere on screen",
    },
    "ventral_visual": {
        "label": "Ventral visual (objects, faces, scenes)",
        "parcels": ["V4", "V8", "VVC", "FFC", "PIT", "VMV1", "VMV2", "VMV3", "LO1", "LO2", "LO3"],
        "hemi": "both",
        "about": "object, face and scene recognition; images, photos, product shots, illustrations",
    },
    "motion_mt": {
        "label": "Motion (MT complex)",
        "parcels": ["MT", "MST", "V4t", "FST"],
        "hemi": "both",
        "about": "visual motion; scrolling, animations, carousels, moving cursor",
    },
    "dorsal_attention": {
        "label": "Dorsal attention / eye movements",
        "parcels": ["FEF", "PEF", "IPS1", "LIPd", "LIPv", "VIP", "MIP", "AIP", "7PC"],
        "hemi": "both",
        "about": "visual search and spatial attention; dense layouts, many targets, pointing",
    },
    "ventral_occipitotemporal_left": {
        "label": "Left ventral occipitotemporal (word-form area)",
        "parcels": ["PH", "TE2p", "FFC", "VVC"],
        "hemi": "left",
        "about": "visual word recognition; blocks of readable text on screen",
    },
    "language_left": {
        "label": "Language network (left)",
        "parcels": ["44", "45", "55b", "SFL", "PSL", "STSdp", "STSvp", "TPOJ1"],
        "hemi": "left",
        "about": "language comprehension; NOTE: text and audio modalities are zeroed in this pipeline",
    },
    "early_auditory": {
        "label": "Early auditory",
        "parcels": ["A1", "LBelt", "MBelt", "PBelt", "RI"],
        "hemi": "both",
        "about": "sound; the recording is silent, so activity here is model prior, not stimulus",
    },
    "prefrontal_executive": {
        "label": "Lateral prefrontal (executive)",
        "parcels": ["8C", "46", "9-46d", "a9-46v", "p9-46v", "IFJa", "IFJp", "8Av", "i6-8"],
        "hemi": "both",
        "about": "working memory, task control; forms, decisions, multi-step tasks",
    },
    "default_mode": {
        "label": "Default mode (medial)",
        "parcels": ["PCV", "31pd", "31pv", "d23ab", "v23ab", "RSC", "10r", "10v", "9m", "8BM", "PGi", "PGs"],
        "hemi": "both",
        "about": "internally directed thought; tends to drop when the screen demands attention",
    },
    "sensorimotor": {
        "label": "Sensorimotor",
        "parcels": ["4", "3a", "3b", "1", "2"],
        "hemi": "both",
        "about": "body and movement; usually quiet for passive viewing",
    },
}


def load_parcels(mne_data: str | os.PathLike | None = None) -> tuple[dict[tuple[str, str], list[int]], list[str]]:
    """Return {(parcel, hemi): fsaverage5 vertex indices} and the ordered list of parcel names."""
    import mne
    import numpy as np

    base = Path(mne_data or os.environ.get("MNE_DATA", "~/mne_data")).expanduser()
    subjects_dir = base / "subjects"
    subjects_dir.mkdir(parents=True, exist_ok=True)
    mne.datasets.fetch_fsaverage(subjects_dir=subjects_dir, verbose="error")
    # accept=True agrees to the HCP-MMP1.0 terms (cite Glasser et al. 2016)
    mne.datasets.fetch_hcp_mmp_parcellation(subjects_dir=subjects_dir, accept=True, verbose="error")
    labels = mne.read_labels_from_annot(
        "fsaverage", "HCPMMP1", hemi="both", subjects_dir=subjects_dir, verbose="error"
    )
    by_name: dict[tuple[str, str], list[int]] = {}
    names: list[str] = []
    for label in labels:  # names look like "L_V1_ROI-lh"
        hemi = "left" if label.name.endswith("-lh") else "right"
        name = label.name[2:].rsplit("-", 1)[0].replace("_ROI", "")
        if name == "???":
            continue
        verts = np.asarray(label.vertices)
        verts = verts[verts < N_HEMI] + (N_HEMI if hemi == "right" else 0)
        by_name[(name, hemi)] = [int(v) for v in verts]
        if name not in names:
            names.append(name)
    return by_name, names


def roi_indices(by_name: dict[tuple[str, str], list[int]]) -> dict[str, list[int]]:
    """Vertex indices per ROI group, built from `load_parcels` output."""
    out: dict[str, list[int]] = {}
    for key, spec in ROI_GROUPS.items():
        hemis = ["left", "right"] if spec["hemi"] == "both" else [spec["hemi"]]
        idx: set[int] = set()
        for p in spec["parcels"]:
            for h in hemis:
                if (p, h) not in by_name:
                    print(f"[hcp] warning: parcel {p!r} ({h}) not in atlas, skipped")
                    continue
                idx.update(by_name[(p, h)])
        out[key] = sorted(idx)
    return out
