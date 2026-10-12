"""LLM provider registry.

    from server.llm import get_provider
    llm = get_provider("qwen3-vl")           # by preset name
    llm.chat_json([Message("user", "...", images=[jpeg_bytes])])
"""

from __future__ import annotations

from ..config import CONFIG
from .base import LLMError, Message, ModelPreset, Provider, load_presets, parse_json
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

PROVIDERS: dict[str, type[Provider]] = {
    OllamaProvider.name: OllamaProvider,
    OpenAICompatProvider.name: OpenAICompatProvider,
}

_PRESETS: dict[str, ModelPreset] | None = None


def presets() -> dict[str, ModelPreset]:
    global _PRESETS
    if _PRESETS is None:
        _PRESETS = load_presets()
    return _PRESETS


def get_provider(preset_name: str) -> Provider:
    try:
        preset = presets()[preset_name]
    except KeyError as e:
        raise LLMError(
            f"unknown model preset {preset_name!r}; known: {sorted(presets())}"
        ) from e
    cls = PROVIDERS.get(preset.provider)
    if cls is None:
        raise LLMError(f"unknown provider {preset.provider!r}; known: {sorted(PROVIDERS)}")
    kwargs = {
        "ollama": {"base_url": CONFIG.ollama_url},
        "openai_compat": {
            "base_url": CONFIG.openai_compat_url,
            "api_key": CONFIG.openai_compat_key,
        },
    }.get(preset.provider, {})
    return cls(preset, **kwargs)


def describe_models() -> list[dict]:
    out = []
    for p in presets().values():
        out.append(
            {
                "name": p.name,
                "provider": p.provider,
                "model": p.model,
                "vision": p.vision,
                "description": p.description,
            }
        )
    return out


__all__ = [
    "LLMError",
    "Message",
    "ModelPreset",
    "Provider",
    "PROVIDERS",
    "describe_models",
    "get_provider",
    "parse_json",
    "presets",
]
