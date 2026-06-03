"""Pluggable image-generation backends.

Mirrors the LLM subsystem: ``[[image]]`` blocks in ``lens.toml`` configure one
or more backends; the :func:`registry.resolve` function returns a
``(descriptor, backend)`` pair for a model id.
"""

from lens.core.image.backend import ImageBackend, ImageError
from lens.core.image.spec import (
    Done,
    Error,
    ImageApiCapabilities,
    ImageDescriptor,
    ImageEvent,
    ImageSpec,
    ItemReady,
    Progress,
)

__all__ = [
    "Done",
    "Error",
    "ImageApiCapabilities",
    "ImageBackend",
    "ImageDescriptor",
    "ImageError",
    "ImageEvent",
    "ImageSpec",
    "ItemReady",
    "Progress",
]
