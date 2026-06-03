"""Speech synthesis request types and ``[[speech]]`` descriptor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SpeechSpec:
    """Backend-agnostic TTS request."""

    text: str
    voice_id: str
    language: str


@dataclass(frozen=True, slots=True)
class SpeechDescriptor:
    """Resolved ``[[speech]]`` config row."""

    id: str
    api: str
    model: str
    grammar: str | None
    max_text_chars: int
    timeout_seconds: float
    refine_llm_id: str | None = None
    default_voice: str | None = None
    extra: dict[str, Any] = field(default_factory=dict[str, Any])
