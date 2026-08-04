"""Project-level configuration for the ``media_attach`` modality (``[modality.media_attach]``)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import tomllib


@dataclass(frozen=True)
class MediaAttachConfig:
    llm: str | None = None
    """``[[llm]]`` id for the classify pass; falls back to the operator LLM when unset."""
    context_beats: int = 2
    """Preceding beats of prose sent as context to the classify pass."""

    @classmethod
    def from_project(cls, project_root: Path) -> "MediaAttachConfig":
        """Read ``[modality.media_attach]`` from *project_root*/lens.toml; fall back to defaults."""
        lens_toml = project_root / "lens.toml"
        if not lens_toml.exists():
            return cls()
        with lens_toml.open("rb") as f:
            config: dict[str, Any] = tomllib.load(f)
        modality = config.get("modality")
        if not isinstance(modality, dict):
            return cls()
        modality_d = cast(dict[str, Any], modality)
        section = modality_d.get("media_attach")
        if not isinstance(section, dict):
            return cls()

        kwargs: dict[str, Any] = {}
        if "llm" in section and isinstance(section["llm"], str):
            kwargs["llm"] = section["llm"]
        if "context_beats" in section and isinstance(section["context_beats"], int):
            kwargs["context_beats"] = section["context_beats"]
        return cls(**kwargs)
