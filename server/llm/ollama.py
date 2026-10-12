"""Ollama backend (http://127.0.0.1:11434 by default)."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from .base import LLMError, Message, ModelPreset, Provider


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, preset: ModelPreset, base_url: str = "http://127.0.0.1:11434", **_: Any):
        super().__init__(preset)
        self.base_url = base_url.rstrip("/")

    def healthy(self) -> tuple[bool, str]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            names = {m["name"] for m in r.json().get("models", [])}
            if self.preset.model in names or self.preset.model.split(":")[0] in {
                n.split(":")[0] for n in names
            }:
                return True, "ok"
            return False, f"model {self.preset.model!r} is not pulled (ollama pull {self.preset.model})"
        except Exception as e:  # noqa: BLE001
            return False, f"ollama unreachable at {self.base_url}: {e}"

    def chat(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: float = 600.0,
    ) -> str:
        msgs = []
        for m in messages:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.images:
                if not self.preset.vision:
                    raise LLMError(f"model preset {self.preset.name!r} has no vision capability")
                entry["images"] = [base64.b64encode(b).decode("ascii") for b in m.images]
            msgs.append(entry)
        options = {"temperature": temperature, "num_predict": max_tokens}
        options.update(self.preset.options)
        payload: dict[str, Any] = {
            "model": self.preset.model,
            "messages": msgs,
            "stream": False,
            "think": False,
            "options": options,
        }
        if json_mode:
            payload["format"] = "json"
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"ollama request failed: {e}") from e
        data = r.json()
        return data.get("message", {}).get("content", "")
