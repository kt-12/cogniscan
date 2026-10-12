"""Unit tests that need no GPU, no Ollama and no Chrome."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from server.agent.marks import elements_to_text, find_element, rank_elements
from server.agent.planner import validate
from server.interpret.stats import make_sentence, step_stats, window_rows
from server.llm import PROVIDERS, presets
from server.llm.base import LLMError, parse_json
from server.pipeline.recorder import load_frames, resample

ELEMENTS = [
    {"id": 1, "tag": "a", "text": "Download", "bbox": {"x": 100, "y": 20, "w": 80, "h": 30}, "inViewport": True},
    {"id": 2, "tag": "input", "placeholder": "Email", "bbox": {"x": 300, "y": 200, "w": 200, "h": 30}, "inViewport": True},
    {"id": 3, "tag": "button", "text": "Sign up", "bbox": {"x": 300, "y": 260, "w": 100, "h": 36}, "inViewport": False},
]


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```')["a"] == 1
    assert parse_json('Sure! {"type": "click", "id": 2} done')["id"] == 2
    assert parse_json('<think>hmm</think>{"x": "y"}')["x"] == "y"
    with pytest.raises(LLMError):
        parse_json("no json here")


def test_presets_and_providers():
    p = presets()
    assert "qwen3-vl" in p and p["qwen3-vl"].vision
    assert {pr.provider for pr in p.values()} <= set(PROVIDERS)


def test_marks_text_and_lookup():
    txt = elements_to_text(rank_elements(ELEMENTS))
    assert "[1] a 'Download'" in txt and "offscreen" in txt
    assert find_element(ELEMENTS, "2")["tag"] == "input"
    assert find_element(ELEMENTS, 99) is None


def test_validate_actions():
    a = validate({"type": "click", "id": 1, "reason": "r", "label": "Download page"}, ELEMENTS)
    assert a["type"] == "click" and a["element"]["text"] == "Download"
    a = validate({"type": "type", "id": 2, "text": "test@example.com", "submit": True}, ELEMENTS)
    assert a["submit"] is True and a["label"]
    a = validate({"type": "click", "id": 42}, ELEMENTS)  # unknown id -> safe fallback
    assert a["type"] == "scroll"
    a = validate({"type": "navigate", "url": "javascript:alert(1)"}, ELEMENTS)
    assert a["type"] == "done"
    a = validate({"type": "key", "key": "F5"}, ELEMENTS)
    assert a["key"] == "Enter"


def test_window_rows_widens_short_steps():
    rows = window_rows(10.2, 10.6, n_rows=60)
    assert len(rows) >= 2 and 10 in rows
    assert window_rows(58.5, 70.0, n_rows=60) == [58, 59]
    assert window_rows(0.0, 0.1, n_rows=1) == [0]


def test_step_stats_and_sentence():
    rng = np.random.default_rng(0)
    n_t, n_v = 20, 20484
    preds = rng.normal(0, 0.1, (n_t, n_v)).astype(np.float32)
    preds[5:8, :5000] += 0.5  # a burst in the first 5000 vertices
    roi_means = {"early_visual": preds[:, :5000].mean(axis=1).tolist(), "default_mode": preds[:, 5000:9000].mean(axis=1).tolist()}
    parcels = {
        "available": True,
        "roi_means": roi_means,
        "roi_groups": {k: {"label": k, "about": ""} for k in roi_means},
        "parcel_means": {"L_V1": preds[:, :2000].mean(axis=1).tolist(), "R_V1": preds[:, 2000:4000].mean(axis=1).tolist(), "L_PCV": preds[:, 5000:6000].mean(axis=1).tolist()},
    }
    tribe = {"preds": preds, "parcels": parcels, "meta": {"TR_s": 1.0}}
    st = step_stats(tribe, 5.0, 8.0)
    assert st["rows"] == [5, 6, 7]
    assert st["rois"][0]["key"] == "early_visual" and st["rois"][0]["z"] > 1
    assert st["top_parcels"][0]["name"] in ("L_V1", "R_V1")
    assert "Early" in make_sentence(st) or "early_visual" in make_sentence(st)


def test_resample_holds_last_frame(tmp_path: Path):
    frames = [(0.0, Path("a")), (0.95, Path("b")), (2.4, Path("c"))]
    slots = resample(frames, fps=2, duration=3.0)
    assert [p.name for p in slots] == ["a", "a", "b", "b", "b", "c"]
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "1.jpg").write_bytes(b"x")
    (tmp_path / "frames.jsonl").write_text(json.dumps({"file": "1.jpg", "t": 0.5}) + "\n" + json.dumps({"file": "missing.jpg", "t": 1}) + "\n")
    assert [t for t, _ in load_frames(tmp_path)] == [0.5]
