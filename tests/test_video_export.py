import numpy as np

from server.pipeline.video_export import (
    caption_for,
    diverging_rgb,
    frame_times,
    interp_weights,
    sulc_base,
)


def test_frame_times_cover_duration():
    t = frame_times(7.3, 10)
    assert len(t) == 73
    assert t[0] == 0 and abs(t[-1] - 7.2) < 1e-9


def test_interp_weights_blend_between_rows():
    a, b, w = interp_weights(0.0, 10)  # before the first row centre: weight 0 → row 0 only
    assert (a, w) == (0, 0.0)
    a, b, w = interp_weights(1.0, 10)  # centre of second 0.5 → half way between rows 0 and 1
    assert (a, b) == (0, 1) and abs(w - 0.5) < 1e-9
    a, b, w = interp_weights(99.0, 10)  # past the end: hold the last row
    assert (a, b, w) == (9, 9, 0.0)
    assert interp_weights(3.0, 1) == (0, 0, 0.0)


def test_caption_for_picks_window_then_latest():
    slides = [
        {"i": 0, "stats": {"t0": 0, "t1": 4}},
        {"i": 1, "stats": {"t0": 4, "t1": 9}},
        {"i": 2, "stats": {"t0": 12, "t1": 15}},
    ]
    assert caption_for(1, slides)["i"] == 0
    assert caption_for(4, slides)["i"] == 1
    assert caption_for(10, slides)["i"] == 1  # gap: latest started slide
    assert caption_for(14, slides)["i"] == 2
    assert caption_for(0, []) is None


def test_diverging_rgb_threshold_and_sign():
    base = np.full((4, 3), 0.6)
    v = np.array([0.0, 0.05, 0.6, -0.6], dtype=np.float32)
    rgb = diverging_rgb(v, thr=0.1, rng=0.6, base=base)
    assert rgb.dtype == np.uint8 and rgb.shape == (4, 3)
    assert (rgb[0] == rgb[1]).all() and rgb[0][0] == int(0.6 * 255)  # below threshold: base grey
    assert rgb[2][0] > rgb[2][2]  # positive: warm (more red than blue)
    assert rgb[3][2] > rgb[3][0]  # negative: cool


def test_sulc_base_darkens_sulci():
    s = np.linspace(-2, 2, 100)
    base = sulc_base(s)
    assert base.shape == (100, 3)
    assert base[0, 0] > base[-1, 0]  # gyri (negative sulc) lighter than sulci
