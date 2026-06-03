"""Abstract base for image-generation backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from lens.core.exceptions import LensException
from lens.core.image.spec import ImageEvent, ImageSpec


class ImageError(LensException):
    """Raised when an image backend fails or is misconfigured."""


class ImageBackend(ABC):
    """Streaming image-generation backend.

    Backends emit a sequence of :class:`ImageEvent` payloads:

    *  :class:`Progress` heartbeats throughout the run,
    *  one :class:`ItemReady` per generated image,
    *  exactly one :class:`Done` on success or :class:`Error` on failure.

    Backends that can't stream incremental items still emit ``Progress``
    heartbeats and a single ``ItemReady`` per result so the consumer surface
    is uniform across providers.
    """

    @abstractmethod
    def generate(self, spec: ImageSpec) -> AsyncIterator[ImageEvent]:
        """Run a generation and yield events as they happen."""
