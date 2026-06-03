"""Image-generation request specs and event types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ImageSpec:
    """Backend-agnostic image-generation request.

    A generic super-set of fields needed by all configured backends.  Backends
    translate these to provider-specific parameters (e.g. A2E maps
    ``aspect_ratio + size`` to ``width/height`` for ``model_type=a2e``).
    """

    prompt: str
    aspect_ratio: str
    size: str
    batch: int
    model_id: str
    negative_prompt: str | None = None
    input_image_urls: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ImageApiCapabilities:
    """Features an image API implementation may support (see ``[[image]].api``)."""

    supports_reference_images: bool = False


@dataclass(frozen=True, slots=True)
class ImageDescriptor:
    """Resolved ``[[image]]`` config row.

    Used by orchestration to validate ``aspect_ratio`` / ``size`` / ``batch``
    against backend capabilities before dispatch, without the backend itself
    needing to re-read the toml.
    """

    id: str
    api: str
    model: str
    aspect_ratios: tuple[str, ...]
    sizes: tuple[str, ...]
    max_prompt_chars: int
    max_batch: int
    timeout_seconds: float
    supports_reference_images: bool = False
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


# ---------------------------------------------------------------------------
# Event variants emitted by ImageBackend.generate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Progress:
    phase: str
    pct: float | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ItemReady:
    index: int
    data: bytes
    ext: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Done:
    pass


@dataclass(frozen=True, slots=True)
class Error:
    message: str


ImageEvent = Progress | ItemReady | Done | Error
