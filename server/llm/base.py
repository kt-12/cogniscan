"""Provider-agnostic LLM interface.

A *provider* is a backend (Ollama, any OpenAI-compatible server). A *model preset* is a named
entry in `models.yaml` that says which provider and model id to use and what it can do.
Adding a model: add a YAML entry. Adding a backend: subclass `Provider` and register it in
`PROVIDERS` (see `__init__.py`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MODELS_FILE = Path(__file__).with_name("models.yaml")


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str
    images: list[bytes] = field(default_factory=list)  # raw JPEG/PNG bytes


@dataclass
class ModelPreset:
    name: str
    provider: str
    model: str
    vision: bool = False
    description: str = ""
    options: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    pass


class Provider:
    """Minimal chat interface every backend implements."""

    name = "base"

    def __init__(self, preset: ModelPreset, **kwargs: Any) -> None:
        self.preset = preset

    def chat(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: float = 600.0,
    ) -> str:
        raise NotImplementedError

    def chat_json(self, messages: list[Message], **kw: Any) -> dict:
        kw.setdefault("json_mode", True)
        text = self.chat(messages, **kw)
        return parse_json(text)

    def healthy(self) -> tuple[bool, str]:
        return True, "ok"


def parse_json(text: str) -> dict:
    """Parse a JSON object out of model output, tolerating fences and prose around it."""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    raise LLMError(f"model did not return a JSON object: {text[:300]!r}")


def load_presets(path: Path = MODELS_FILE) -> dict[str, ModelPreset]:
    raw = yaml.safe_load(path.read_text()) or {}
    presets = {}
    for name, spec in (raw.get("models") or {}).items():
        presets[name] = ModelPreset(
            name=name,
            provider=spec["provider"],
            model=spec["model"],
            vision=bool(spec.get("vision", False)),
            description=spec.get("description", ""),
            options=dict(spec.get("options") or {}),
        )
    return presets
