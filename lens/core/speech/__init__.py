"""Pluggable speech (TTS) backends via ``[[speech]]`` in ``lens.toml``."""

from lens.core.speech.backend import SpeechBackend, SpeechError
from lens.core.speech.spec import SpeechDescriptor, SpeechSpec

__all__ = [
    "SpeechBackend",
    "SpeechDescriptor",
    "SpeechError",
    "SpeechSpec",
]
