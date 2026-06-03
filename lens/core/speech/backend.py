"""Abstract speech synthesis backend."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lens.core.exceptions import LensException
from lens.core.speech.spec import SpeechSpec


class SpeechError(LensException):
    """Raised when speech configuration or synthesis fails."""


class SpeechBackend(ABC):
    @abstractmethod
    def synthesize(self, spec: SpeechSpec) -> bytes:
        """Return raw audio bytes (e.g. MP3) for *spec*."""
