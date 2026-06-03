"""Automated compression: size-based triggering and config for the compress operator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

import tomllib

from lens.core.annotations import strip_markdown_comments


class Aggressiveness(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class CompressConfig:
    unit: str = "bytes"
    sm: int = 15_000   # ~3k tokens — min child section / meaningful growth delta
    m: int = 40_000    # ~8k tokens — low aggressiveness begins
    lg: int = 80_000   # ~16k tokens — medium aggressiveness begins (TOML key: "l")
    xl: int = 150_000  # ~30k tokens — high aggressiveness (must act)
    auto_compress: bool = True

    @classmethod
    def from_project(cls, project_root: Path) -> "CompressConfig":
        """Read ``[compress]`` from *project_root*/lens.toml; fall back to defaults."""
        lens_toml = project_root / "lens.toml"
        if not lens_toml.exists():
            return cls()
        with lens_toml.open("rb") as f:
            config: dict[str, Any] = tomllib.load(f)
        section = config.get("compress")
        if not isinstance(section, dict):
            return cls()

        kwargs: dict[str, Any] = {}
        for int_key in ("sm", "m", "xl"):
            if int_key in section and isinstance(section[int_key], int):
                kwargs[int_key] = section[int_key]
        # TOML key "l" maps to Python field "lg" (avoids E741 ambiguous name lint).
        if "l" in section and isinstance(section["l"], int):
            kwargs["lg"] = section["l"]
        if "unit" in section and isinstance(section["unit"], str):
            kwargs["unit"] = section["unit"]
        if "auto_compress" in section and isinstance(section["auto_compress"], bool):
            kwargs["auto_compress"] = section["auto_compress"]
        return cls(**kwargs)


def get_visible_text(node_text: str) -> str:
    """Strip markdown comment annotations; return visible text."""
    return strip_markdown_comments(node_text)


def measure_visible_bytes(visible_text: str) -> int:
    """UTF-8 byte length of *visible_text*."""
    return len(visible_text.encode("utf-8"))


def get_last_compress_size(fm: dict[str, Any]) -> int | None:
    """Extract ``compress.last_size`` from a parsed front matter dict."""
    compress_fm = fm.get("compress")
    if not isinstance(compress_fm, dict):
        return None
    inner = cast(dict[str, Any], compress_fm)
    val = inner.get("last_size")
    if isinstance(val, int):
        return val
    return None


def auto_compress_enabled(config: CompressConfig, node_fm: dict[str, Any]) -> bool:
    """Whether auto-compress may run after write/play/chat: per-node FM overrides project."""
    compress_fm = node_fm.get("compress")
    if isinstance(compress_fm, dict):
        inner = cast(dict[str, Any], compress_fm)
        raw = inner.get("auto_compress")
        if isinstance(raw, bool):
            return raw
    return config.auto_compress


def should_trigger(
    current_size: int,
    last_size: int | None,
    config: CompressConfig,
) -> Aggressiveness | None:
    """Return an :class:`Aggressiveness` level when auto-compress should fire, else ``None``.

    Logic:
    - current_size < m → None (node is small enough, never trigger)
    - current_size > xl → HIGH (must act immediately, no delta check)
    - m ≤ current_size ≤ lg → LOW (fire only when growth ≥ sm since last compress)
    - lg < current_size ≤ xl → MEDIUM (fire only when growth ≥ sm since last compress)

    "delta ok" means *last_size* is ``None`` (never compressed) or
    ``current_size - last_size >= sm``.
    """
    if current_size < config.m:
        return None
    if current_size > config.xl:
        return Aggressiveness.HIGH
    delta_ok = last_size is None or (current_size - last_size) >= config.sm
    if not delta_ok:
        return None
    if current_size <= config.lg:
        return Aggressiveness.LOW
    return Aggressiveness.MEDIUM


def build_auto_directive(
    store: Any,  # PromptStore — avoid circular import
    aggressiveness: Aggressiveness,
    config: CompressConfig,
) -> str:
    """Format the auto directive template for the given aggressiveness level."""
    key = f"compress.auto_directive_{aggressiveness.value}"
    return store.format(key, sm=config.sm, m=config.m)
