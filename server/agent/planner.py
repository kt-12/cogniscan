"""Pick the next browser action from a screenshot + numbered element list.

Stateless: the extension sends the history every step. Returns a validated action dict:
    {type: click|type|scroll|key|navigate|wait|done, id?, text?, submit?, direction?, key?, url?,
     reason, label}
`label` is a 2-6 word description of what this step shows, used as the slide caption.
"""

from __future__ import annotations

from ..llm import LLMError, Message, get_provider
from .marks import elements_to_text, find_element, rank_elements

ACTIONS = {"click", "type", "scroll", "key", "navigate", "wait", "done"}

SCHEMA = (
    'Reply with ONE JSON object: {"type": "click"|"type"|"scroll"|"key"|"navigate"|"wait"|"done", '
    '"id": <element number for click/type>, "text": <text for type>, "submit": <true to press Enter after typing>, '
    '"direction": "up"|"down" (scroll), "key": <"Enter"|"Escape"|"Tab"> (key), "url": <for navigate>, '
    '"reason": <one sentence>, "label": <2-6 words naming what this step shows, e.g. "Pricing page", '
    '"Sign-up form filled">}. Use element numbers exactly as listed. Never invent numbers.'
)

GOAL_SYSTEM = (
    "You control a web browser with a virtual mouse to accomplish the user's goal on this site. "
    "You see a screenshot with red numbered badges on interactive elements and the same list as text. "
    "Prefer the single most direct action. Dismiss cookie banners or modals first if they block content. "
    "Do not log in with real credentials; use the test values given in the goal, or placeholder values "
    "like test@example.com if the goal asks you to fill a form. Never submit payments. "
    "Scroll when the needed element is offscreen or not listed. When the goal is reached, or cannot be "
    "reached in a few more steps, reply with type 'done' and say why. "
    + SCHEMA
)

EXPLORE_SYSTEM = (
    "You are exploring a website to record its main user flows for a visual study. "
    "You see a screenshot with red numbered badges on interactive elements and the same list as text. "
    "Plan: (1) dismiss cookie banners/modals; (2) scroll the landing page once; (3) open the most "
    "important top-navigation pages in turn (product, pricing, features, about, docs or similar); "
    "(4) open one primary call-to-action (sign up, get started, try, buy) and look at the form without "
    "submitting; (5) stop. Avoid pages you already visited (see history). Avoid external links, "
    "downloads, logouts, and anything destructive. Never submit payments. "
    "After roughly 8-12 steps, or when the main flows are covered, reply with type 'done'. "
    + SCHEMA
)


def _history_text(history: list[dict]) -> str:
    if not history:
        return "(none yet)"
    lines = []
    for h in history[-10:]:
        a = h.get("action", {})
        lines.append(f"{h.get('i', 0) + 1}. {a.get('type')} {a.get('id', '')} {a.get('text', '')} -> {h.get('label', '')} ({h.get('url', '')})")
    return "\n".join(lines)


def _stuck(history: list[dict]) -> bool:
    if len(history) < 3:
        return False
    last = [(h.get("action", {}).get("type"), h.get("action", {}).get("id"), h.get("url")) for h in history[-3:]]
    return len(set(last)) == 1


def next_action(
    *,
    mode: str,
    goal: str,
    url: str,
    title: str,
    elements: list[dict],
    history: list[dict],
    screenshot: bytes | None,
    model: str,
    step_index: int,
    max_steps: int,
    seconds_left: float,
) -> dict:
    llm = get_provider(model)
    ranked = rank_elements(elements)
    system = GOAL_SYSTEM if mode == "goal" else EXPLORE_SYSTEM
    budget = f"Step {step_index + 1} of at most {max_steps}; {seconds_left:.0f} s of recording time left."
    if seconds_left < 8 or step_index >= max_steps - 1:
        budget += " You MUST reply with type 'done' now."
    elif _stuck(history):
        budget += " The last actions repeated without effect: do something different (scroll, another element, or done)."
    user = (
        f"Goal: {goal or '(explore the site)'}\nCurrent page: {title} — {url}\n{budget}\n\n"
        f"History:\n{_history_text(history)}\n\nInteractive elements:\n{elements_to_text(ranked)}\n\n"
        "What is the next action?"
    )
    images = [screenshot] if (screenshot and llm.preset.vision) else []
    try:
        raw = llm.chat_json(
            [Message("system", system), Message("user", user, images=images)],
            temperature=0.1,
            max_tokens=300,
            timeout=300,
        )
    except LLMError as e:
        return {"type": "done", "reason": f"model error: {e}", "label": "Stopped", "error": True}
    return validate(raw, elements)


def validate(raw: dict, elements: list[dict]) -> dict:
    t = str(raw.get("type", "")).lower().strip()
    if t not in ACTIONS:
        return {"type": "done", "reason": f"model returned unknown action {t!r}", "label": "Stopped"}
    action: dict = {
        "type": t,
        "reason": str(raw.get("reason", ""))[:300],
        "label": str(raw.get("label", "") or "")[:60],
    }
    if t in ("click", "type"):
        el = find_element(elements, raw.get("id"))
        if el is None:
            return {
                "type": "scroll",
                "direction": "down",
                "reason": f"model chose element {raw.get('id')!r} which is not on the list; scrolling instead",
                "label": action["label"] or "Scrolling",
            }
        action["id"] = int(el["id"])
        action["element"] = el
        if t == "type":
            action["text"] = str(raw.get("text", ""))[:500]
            action["submit"] = bool(raw.get("submit", False))
    elif t == "scroll":
        action["direction"] = "up" if str(raw.get("direction", "down")).lower() == "up" else "down"
    elif t == "key":
        k = str(raw.get("key", "Enter"))
        action["key"] = k if k in ("Enter", "Escape", "Tab", "Backspace", "ArrowDown", "ArrowUp") else "Enter"
    elif t == "navigate":
        u = str(raw.get("url", ""))
        if not u.startswith(("http://", "https://")):
            return {"type": "done", "reason": "invalid navigate url", "label": "Stopped"}
        action["url"] = u
    elif t == "wait":
        action["ms"] = int(min(5000, max(300, raw.get("ms", 1500) or 1500)))
    if not action["label"]:
        action["label"] = {
            "click": "Clicked an element",
            "type": "Typed into a field",
            "scroll": "Scrolled the page",
            "key": "Pressed a key",
            "navigate": "Opened a page",
            "wait": "Waited",
            "done": "Finished",
        }[t]
    return action
