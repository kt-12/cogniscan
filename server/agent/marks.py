"""Set-of-marks helpers: the content script numbers interactive elements; we turn that list into
compact prompt text and validate the model's chosen id."""

from __future__ import annotations

MAX_ELEMENTS = 90


def _short(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def rank_elements(elements: list[dict]) -> list[dict]:
    """Keep the most useful elements: visible, in viewport first, then by size and text."""
    def key(e: dict):
        bb = e.get("bbox") or {}
        area = max(1.0, float(bb.get("w", 0)) * float(bb.get("h", 0)))
        has_text = 1 if (e.get("text") or e.get("name") or e.get("placeholder")) else 0
        in_view = 1 if e.get("inViewport", True) else 0
        return (-in_view, -has_text, -min(area, 40000))

    return sorted(elements, key=key)[:MAX_ELEMENTS]


def elements_to_text(elements: list[dict]) -> str:
    lines = []
    for e in elements:
        tag = e.get("tag", "el")
        role = e.get("role") or ""
        label = e.get("text") or e.get("name") or e.get("placeholder") or e.get("href") or ""
        extra = []
        if role and role != tag:
            extra.append(role)
        if e.get("type") and e["type"] not in ("", "text"):
            extra.append(e["type"])
        if e.get("value"):
            extra.append(f"value='{_short(e['value'], 20)}'")
        if not e.get("inViewport", True):
            extra.append("offscreen")
        bb = e.get("bbox") or {}
        pos = f"@{int(bb.get('x', 0))},{int(bb.get('y', 0))}" if bb else ""
        meta = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"[{e['id']}] {tag}{meta} '{_short(label, 70)}' {pos}")
    return "\n".join(lines)


def find_element(elements: list[dict], el_id) -> dict | None:
    try:
        el_id = int(el_id)
    except (TypeError, ValueError):
        return None
    for e in elements:
        if int(e.get("id", -1)) == el_id:
            return e
    return None
