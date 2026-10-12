"""LLM interpretation of per-step TRIBE statistics.

The model never sees raw predictions, only the numbers in `stats.step_stats`, the step's action,
the page screenshot (if the model has vision) and a fixed list of caveats. Output is short JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..llm import LLMError, Message, get_provider

CAVEATS = (
    "TRIBE v2 predicts the average-subject fMRI response to the video of the screen. "
    "Only the video modality carries information here: the recording is silent and the text "
    "encoder is not loaded, so activity in auditory or language areas reflects the model's prior "
    "and visual input, NOT comprehension of words or sounds. "
    "BOLD is slow: each second blends several seconds of content around it. "
    "Numbers are relative to this run's own baseline (z-scores), not absolute. "
    "This is not an engagement, emotion, attention, cognitive-load or quality score; never claim users "
    "'feel', 'struggle', are 'engaged' or 'loaded'. Describe which visual and attentional processes the "
    "screen content likely recruits (edges/contrast, motion, objects/faces, text-shaped input, spatial "
    "search) and tie each claim to a specific region and to what is visible on the page."
)

SYSTEM = (
    "You are a cognitive-neuroscience analyst explaining predicted brain responses to a web page "
    "for a product and UX audience. Be concrete, cautious and plain-spoken. "
    + CAVEATS
    + " Reply with JSON: {\"headline\": <max 8 words>, \"interpretation\": <70-110 words>, "
    "\"ux_note\": <one sentence actionable observation about the page or step, or empty>, "
    "\"confidence\": \"low\"|\"medium\"|\"high\"}."
)

SUMMARY_SYSTEM = (
    "You are a cognitive-neuroscience analyst summarising a whole web flow. "
    + CAVEATS
    + " Reply with JSON: {\"summary\": <120-180 words comparing the steps>, "
    "\"notable_steps\": [{\"step\": <int>, \"why\": <short>}], \"caveat\": <one sentence>}."
)


def _roi_block(st: dict) -> str:
    lines = []
    for r in st["rois"]:
        lines.append(f"- {r['label']}: z={r['z']:+.2f} (window mean {r['mean']:+.3f}); {r['about']}")
    top = ", ".join(f"{p['name']} (z {p['z']:+.1f})" for p in st["top_parcels"][:5])
    bottom = ", ".join(f"{p['name']} (z {p['z']:+.1f})" for p in st["bottom_parcels"][:3])
    return (
        "\n".join(lines)
        + f"\nStrongest parcels (HCP-MMP1): {top}\nWeakest parcels: {bottom}\n"
        f"Overall predicted activity z={st['mean_abs_z']:+.2f}; spatial spread {st['spatial_std']:.3f}; "
        f"window {st['t0']}-{st['t1']} s; peak at {st['peak_second']} s."
    )


def describe_action(step: dict) -> str:
    a = step.get("action", {}) or {}
    t = a.get("type", "?")
    el = step.get("element") or {}
    label = el.get("text") or el.get("name") or el.get("tag") or ""
    if t == "click":
        return f"clicked {el.get('tag', 'element')} '{label[:60]}'"
    if t == "type":
        return f"typed '{a.get('text', '')[:40]}' into {el.get('tag', 'field')} '{label[:40]}'"
    if t == "scroll":
        return f"scrolled {a.get('direction', 'down')}"
    if t == "navigate":
        return f"navigated to {a.get('url', '')}"
    if t == "key":
        return f"pressed {a.get('key', '')}"
    if t == "wait":
        return "waited for the page"
    if t == "done":
        return "finished: " + str(a.get("reason", ""))[:80]
    return t


def interpret_step(step: dict, st: dict, run: dict, *, model: str, image: bytes | None = None) -> dict:
    llm = get_provider(model)
    content = (
        f"Site: {run.get('url', '')}\nGoal: {run.get('goal') or run.get('mode')}\n"
        f"Step {step['i'] + 1}: {describe_action(step)}\nPage: {step.get('title', '')} ({step.get('url', '')})\n"
        f"What the screen looked like: {step.get('label', '') or 'see screenshot'}\n\n"
        f"TRIBE statistics for this step:\n{_roi_block(st)}\n\n"
        "Explain what these predicted responses say about how this page/step is processed visually."
    )
    images = [image] if (image and llm.preset.vision) else []
    try:
        data = llm.chat_json(
            [Message("system", SYSTEM), Message("user", content, images=images)],
            temperature=0.3,
            max_tokens=600,
        )
    except LLMError as e:
        return {
            "headline": "Interpretation unavailable",
            "interpretation": f"The interpretation model failed: {e}",
            "ux_note": "",
            "confidence": "low",
            "model": model,
            "error": str(e),
        }
    data.setdefault("headline", "")
    data.setdefault("interpretation", "")
    data.setdefault("ux_note", "")
    data.setdefault("confidence", "low")
    data["model"] = model
    return data


def interpret_run(run: dict, steps: list[dict], per_step: list[dict], rstats: dict, *, model: str) -> dict:
    llm = get_provider(model)
    lines = []
    for s, st in zip(steps, per_step, strict=False):
        up = ", ".join(f"{r['label']} {r['z']:+.1f}" for r in st["rois"][:3])
        lines.append(
            f"Step {s['i'] + 1} ({st['t0']}-{st['t1']} s): {describe_action(s)}; overall z={st['mean_abs_z']:+.2f}; "
            f"top: {up}"
        )
    content = (
        f"Site: {run.get('url', '')}\nMode: {run.get('mode')}; goal: {run.get('goal') or '-'}\n"
        f"Strongest overall response at step {rstats.get('strongest_step', 0) + 1}, weakest at step "
        f"{rstats.get('weakest_step', 0) + 1}.\n\n" + "\n".join(lines)
    )
    try:
        data = llm.chat_json(
            [Message("system", SUMMARY_SYSTEM), Message("user", content)],
            temperature=0.3,
            max_tokens=700,
        )
    except LLMError as e:
        data = {"summary": f"Summary unavailable: {e}", "notable_steps": [], "caveat": ""}
    data["model"] = model
    return data


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1))
