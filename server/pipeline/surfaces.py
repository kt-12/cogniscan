"""GIfTI / FreeSurfer-curv helpers shared by the mesh export and the TRIBE worker.

Executed inside the TRIBE interpreter (needs nibabel + numpy); imports are kept inside the functions
so the module can still be imported by the FastAPI process for path constants.

Files produced (NiiVue reads all of them directly):
    static/surf/{lh,rh}.inflated.surf.gii   fsaverage5 inflated hemisphere (POINTSET + TRIANGLE)
    static/surf/{lh,rh}.sulc.curv           sulcal depth, FreeSurfer curv format
    static/surf/parcels.json                 HCP-MMP1 parcel id per vertex per hemisphere + ROI groups
    runs/<id>/tribe/{lh,rh}.func.gii         TRIBE predictions, one float32 DataArray per second
"""

from __future__ import annotations

from pathlib import Path

N_HEMI = 10242
HEMIS = ("lh", "rh")


def write_surf_gii(path: Path, coords, faces) -> None:
    import nibabel as nib
    import numpy as np
    from nibabel.gifti import GiftiDataArray, GiftiImage

    pts = GiftiDataArray(np.ascontiguousarray(coords, dtype=np.float32), intent="NIFTI_INTENT_POINTSET",
                         datatype="NIFTI_TYPE_FLOAT32")
    tri = GiftiDataArray(np.ascontiguousarray(faces, dtype=np.int32), intent="NIFTI_INTENT_TRIANGLE",
                         datatype="NIFTI_TYPE_INT32")
    nib.save(GiftiImage(darrays=[pts, tri]), str(path))


def write_curv(path: Path, values, n_faces: int) -> None:
    from nibabel.freesurfer.io import write_morph_data

    write_morph_data(str(path), values, fnum=n_faces)


def write_func_gii(path: Path, series) -> int:
    """series: (nT, N_HEMI) float32 → one DataArray per row. Returns nT."""
    import nibabel as nib
    import numpy as np
    from nibabel.gifti import GiftiDataArray, GiftiImage

    series = np.asarray(series, dtype=np.float32)
    assert series.ndim == 2 and series.shape[1] == N_HEMI, series.shape
    darrays = [
        GiftiDataArray(np.ascontiguousarray(row), intent="NIFTI_INTENT_TIME_SERIES",
                       datatype="NIFTI_TYPE_FLOAT32", encoding="GIFTI_ENCODING_B64GZ")
        for row in series
    ]
    nib.save(GiftiImage(darrays=darrays), str(path))
    return int(series.shape[0])


def write_pred_hemispheres(out_dir: Path, preds) -> dict:
    """Split (nT, 2*N_HEMI) predictions into lh/rh func.gii files in out_dir."""
    out_dir = Path(out_dir)
    n = {}
    for h, hemi in enumerate(HEMIS):
        n[hemi] = write_func_gii(out_dir / f"{hemi}.func.gii", preds[:, h * N_HEMI:(h + 1) * N_HEMI])
    return n
