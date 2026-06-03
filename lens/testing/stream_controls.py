"""Parse mock-LLM stream directives embedded in request message text."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKENS_RE = re.compile(r"\btokens=(\d+)\b", re.IGNORECASE)
_TPS_RE = re.compile(r"\btps=([\d.]+)\b", re.IGNORECASE)

LOREM_WORDS: tuple[str, ...] = tuple(
    "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua Ut enim ad minim "
    "veniam quis nostrud exercitation ullamco laboris".split()
)


@dataclass(frozen=True)
class StreamControls:
    """Streaming shape for the mock LLM (one SSE chunk per token/word)."""

    tokens: int
    tps: float | None = None

    def delay_seconds(self, *, fallback_delay: float = 0.0) -> float:
        if self.tps is not None and self.tps > 0:
            return 1.0 / self.tps
        return fallback_delay


def parse_stream_controls(text: str) -> StreamControls | None:
    """Return controls when ``tokens=N`` appears in *text* (optional ``tps=Y``)."""
    tokens_m = _TOKENS_RE.search(text)
    if not tokens_m:
        return None
    tokens = int(tokens_m.group(1))
    if tokens < 0:
        tokens = 0
    tps_m = _TPS_RE.search(text)
    tps = float(tps_m.group(1)) if tps_m else None
    if tps is not None and tps <= 0:
        tps = None
    return StreamControls(tokens=tokens, tps=tps)


def merge_stream_controls(
    text: str,
    *,
    default_tokens: int | None = None,
    default_tps: float | None = None,
) -> StreamControls | None:
    """Prompt directives win; otherwise apply server defaults."""
    parsed = parse_stream_controls(text)
    if parsed is not None:
        if parsed.tps is None and default_tps is not None and default_tps > 0:
            return StreamControls(tokens=parsed.tokens, tps=default_tps)
        return parsed
    if default_tokens is not None and default_tokens > 0:
        tps = default_tps if default_tps is not None and default_tps > 0 else None
        return StreamControls(tokens=default_tokens, tps=tps)
    return None


def lorem_token_text(token_count: int, *, suffix: str = "") -> str:
    """Build *token_count* words cycling through :data:`LOREM_WORDS`."""
    if token_count <= 0:
        return suffix
    parts = [LOREM_WORDS[i % len(LOREM_WORDS)] for i in range(token_count)]
    body = " ".join(parts)
    return f"{body}{suffix}" if suffix else body
