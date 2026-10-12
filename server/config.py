"""Runtime configuration for scanmyweb.

Values come from, in increasing priority: defaults below, `scanmyweb.toml` in the repo root,
`scanmyweb.local.toml` (gitignored), then environment variables named `SCANMYWEB_<KEY>`.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIBE_EVAL = Path(os.environ.get("TRIBE_EVAL_DIR", str(Path.home() / "tribev2-eval")))


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = ROOT / "data" / "runs"
    static_dir: Path = ROOT / "server" / "static"

    # The TRIBE v2 worker runs in its own interpreter (the one that has torch + tribev2 installed).
    tribe_python: Path = TRIBE_EVAL / ".venv" / "bin" / "python"
    tribe_cache: Path = TRIBE_EVAL / "cache"  # neuralset feature cache
    hf_home: Path = TRIBE_EVAL / "hf_cache"
    mne_data: Path = TRIBE_EVAL / "mne_data"
    nilearn_data: Path = TRIBE_EVAL / "nilearn_data"
    tribe_checkpoint: str = "facebook/tribev2"

    # Recording limits (the extension also enforces these client-side).
    max_flow_seconds: float = 90.0
    max_steps: int = 20
    video_fps: int = 10
    video_max_height: int = 720

    # LLM selection: names refer to entries in server/llm/models.yaml.
    nav_model: str = "qwen3-vl"
    interp_model: str = "qwen3-vl"
    ollama_url: str = "http://127.0.0.1:11434"
    openai_compat_url: str = "http://127.0.0.1:8000/v1"
    openai_compat_key: str = "none"

    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> Config:
        cfg = cls()
        for name in ("scanmyweb.toml", "scanmyweb.local.toml"):
            p = ROOT / name
            if p.exists():
                cfg._apply(tomllib.loads(p.read_text()))
        env = {
            f.name: os.environ[f"SCANMYWEB_{f.name.upper()}"]
            for f in fields(cls)
            if f"SCANMYWEB_{f.name.upper()}" in os.environ
        }
        cfg._apply(env)
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        return cfg

    def _apply(self, values: dict) -> None:
        for f in fields(self):
            if f.name not in values or f.name == "extra":
                continue
            raw = values[f.name]
            if f.type in ("Path", Path):
                raw = Path(str(raw)).expanduser()
            elif f.type in ("int", int):
                raw = int(raw)
            elif f.type in ("float", float):
                raw = float(raw)
            setattr(self, f.name, raw)
        self.extra.update({k: v for k, v in values.items() if k not in {f.name for f in fields(self)}})

    def worker_env(self) -> dict[str, str]:
        """Environment for subprocesses that run inside the TRIBE interpreter."""
        env = dict(os.environ)
        env.update(
            HF_HOME=str(self.hf_home),
            MNE_DATA=str(self.mne_data),
            NILEARN_DATA=str(self.nilearn_data),
            MPLBACKEND="Agg",
            TOKENIZERS_PARALLELISM="false",
            PYTHONUNBUFFERED="1",
        )
        return env


CONFIG = Config.load()
