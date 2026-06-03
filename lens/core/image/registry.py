"""Load ``[[image]]`` config blocks and resolve them to backend instances."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, cast

from lens.core.image.api.a2e import API_CAPABILITIES as A2E_API_CAPABILITIES
from lens.core.image.backend import ImageBackend, ImageError
from lens.core.image.spec import ImageApiCapabilities, ImageDescriptor

# Register each ``[[image]].api`` value that supports optional features; keep in
# sync with ``_build_backend``.
_IMAGE_API_CAPABILITIES: dict[str, ImageApiCapabilities] = {
    "a2e": A2E_API_CAPABILITIES,
}


def _capabilities_for_api(api: str) -> ImageApiCapabilities:
    return _IMAGE_API_CAPABILITIES.get(api, ImageApiCapabilities())


def _load_image_block(project_root: Path, image_id: str | None) -> dict[str, Any]:
    """Return the raw ``[[image]]`` block matching *image_id* (first if ``None``)."""
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        raise ImageError("lens.toml not found; run 'lens init' first")
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)

    raw_list = config.get("image", [])
    image_list: list[dict[str, Any]] = (
        cast(list[dict[str, Any]], raw_list) if isinstance(raw_list, list) else []
    )
    if not image_list:
        raise ImageError(
            "no [[image]] entries found in lens.toml; "
            "add at least one image backend configuration"
        )

    if image_id is None or image_id == "" or image_id == "[default]":
        return image_list[0]

    for entry in image_list:
        if entry.get("id") == image_id:
            return entry
    ids = [str(e.get("id", "")) for e in image_list]
    raise ImageError(
        f"no [[image]] entry with id={image_id!r} in lens.toml "
        f"(configured ids: {ids})"
    )


def _build_descriptor(raw: dict[str, Any]) -> ImageDescriptor:
    api = str(raw.get("api", "")).strip()
    if not api:
        raise ImageError("[[image]] entry is missing required field 'api'")
    model = str(raw.get("model", "")).strip()
    if not model:
        raise ImageError("[[image]] entry is missing required field 'model'")

    aspect_ratios_raw = raw.get("aspect_ratios", [])
    if not isinstance(aspect_ratios_raw, list) or not aspect_ratios_raw:
        raise ImageError("[[image]] entry must define non-empty 'aspect_ratios'")
    aspect_ratios = tuple(str(x) for x in cast(list[Any], aspect_ratios_raw))

    sizes_raw = raw.get("sizes", [])
    if not isinstance(sizes_raw, list) or not sizes_raw:
        raise ImageError("[[image]] entry must define non-empty 'sizes'")
    sizes = tuple(str(x) for x in cast(list[Any], sizes_raw))

    max_prompt_chars = int(raw.get("max_prompt_chars", 2000))
    max_batch = int(raw.get("max_batch", 8))
    timeout_seconds = float(raw.get("timeout_seconds", 300))

    descriptor_id = str(raw.get("id") or "[default]")
    caps = _capabilities_for_api(api)

    extras = {
        k: v
        for k, v in raw.items()
        if k
        not in {
            "id",
            "api",
            "model",
            "api_key_env",
            "aspect_ratios",
            "sizes",
            "max_prompt_chars",
            "max_batch",
            "timeout_seconds",
        }
    }

    return ImageDescriptor(
        id=descriptor_id,
        api=api,
        model=model,
        aspect_ratios=aspect_ratios,
        sizes=sizes,
        max_prompt_chars=max_prompt_chars,
        max_batch=max_batch,
        timeout_seconds=timeout_seconds,
        supports_reference_images=caps.supports_reference_images,
        extra=extras,
    )


def _resolve_api_key(raw: dict[str, Any]) -> str:
    env = str(raw.get("api_key_env", "")).strip()
    if not env:
        raise ImageError(
            "[[image]] entry is missing required field 'api_key_env' "
            "(name of the environment variable holding the API key)"
        )
    key = os.environ.get(env, "")
    if not key:
        raise ImageError(
            f"environment variable {env!r} "
            f"(configured in [[image]] api_key_env) is not set"
        )
    return key


def _build_backend(raw: dict[str, Any], descriptor: ImageDescriptor) -> ImageBackend:
    api = descriptor.api
    api_key = _resolve_api_key(raw)
    if api == "a2e":
        from lens.core.image.api.a2e import A2EBackend

        base_url = str(raw.get("base_url", "https://video.a2e.ai")).rstrip("/")
        return A2EBackend(
            api_key=api_key,
            base_url=base_url,
            model_type=descriptor.model,
            timeout_seconds=descriptor.timeout_seconds,
        )
    raise ImageError(
        f"unknown image api={api!r}; supported: 'a2e'"
    )


def resolve(
    project_root: Path, image_id: str | None = None
) -> tuple[ImageDescriptor, ImageBackend]:
    """Resolve *image_id* (or the default) to a (descriptor, backend) pair."""
    raw = _load_image_block(project_root, image_id)
    descriptor = _build_descriptor(raw)
    backend = _build_backend(raw, descriptor)
    return descriptor, backend


def load_descriptor(
    project_root: Path, image_id: str | None = None
) -> ImageDescriptor:
    """Resolve *image_id* to its descriptor without instantiating a backend.

    Useful for stats / introspection where API keys may not be available.
    """
    raw = _load_image_block(project_root, image_id)
    return _build_descriptor(raw)


def list_image_backend_rows(project_root: Path) -> list[dict[str, Any]]:
    """Return one JSON-friendly dict per valid ``[[image]]`` block (no API key).

    Invalid blocks are skipped so stats/UI still load when one entry is broken.
    """
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return []
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_list = config.get("image", [])
    image_list: list[Any] = cast(list[Any], raw_list) if isinstance(raw_list, list) else []

    out: list[dict[str, Any]] = []
    for raw_any in image_list:
        if not isinstance(raw_any, dict):
            continue
        raw = cast(dict[str, Any], raw_any)
        try:
            d = _build_descriptor(raw)
        except ImageError:
            continue
        out.append(
            {
                "id": d.id,
                "api": d.api,
                "model": d.model,
                "aspect_ratios": list(d.aspect_ratios),
                "sizes": list(d.sizes),
                "default_aspect": d.aspect_ratios[0],
                "default_size": d.sizes[0],
                "default_batch": 1,
                "max_batch": d.max_batch,
                "max_prompt_chars": d.max_prompt_chars,
                "supports_reference_images": d.supports_reference_images,
            }
        )
    return out
