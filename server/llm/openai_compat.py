"""OpenAI-compatible chat backend (vLLM, LM Studio, llama.cpp server, SGLang, ...)."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from .base import LLMError, Message, ModelPreset, Provider


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def __init__(
        self,
        preset: ModelPreset,
        base_url: str = "http://127.0.0.1:8000/v1",
        api_key: str = "none",
        **_: Any,
    ):
        super().__init__(preset)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def healthy(self) -> tuple[bool, str]:
        try:
            r = httpx.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5,
            )
            r.raise_for_status()
            return True, "ok"
        except Exception as e:  # noqa: BLE001
            return False, f"endpoint unreachable at {self.base_url}: {e}"

    def chat(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: float = 600.0,
    ) -> str:
        msgs: list[dict[str, Any]] = []
        for m in messages:
            if m.images:
                if not self.preset.vision:
                    raise LLMError(f"model preset {self.preset.name!r} has no vision capability")
                parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
                for img in m.images:
                    b64 = base64.b64encode(img).decode("ascii")
                    parts.append(
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                    )
                msgs.append({"role": m.role, "content": parts})
            else:
                msgs.append({"role": m.role, "content": m.content})
        payload: dict[str, Any] = {
            "model": self.preset.model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        payload.update(self.preset.options)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"openai-compatible request failed: {e}") from e
        data = r.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected response: {data}") from e
