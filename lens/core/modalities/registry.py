"""Modality registry. Catalog modules self-register on import (see :mod:`lens.core.modalities.catalog`)."""

from __future__ import annotations

from lens.core.modalities.base import Modality


_REGISTRY: dict[str, Modality] = {}


def register_modality(modality: Modality) -> None:
    _REGISTRY[modality.id] = modality


def builtin_modality_ids() -> frozenset[str]:
    """Ids of registered modalities with ``builtin=True`` (default-on stack)."""
    return frozenset(mid for mid, mod in _REGISTRY.items() if mod.builtin)


def get_modality(modality_id: str) -> Modality | None:
    return _REGISTRY.get(modality_id)


def get_modality_or_raise(modality_id: str) -> Modality:
    mod = _REGISTRY.get(modality_id)
    if mod is None:
        raise KeyError(f"unknown modality {modality_id!r}")
    return mod


def registered_ids() -> frozenset[str]:
    return frozenset(_REGISTRY)


def clear_registry_for_tests() -> None:
    """Remove all modalities (tests only)."""
    _REGISTRY.clear()
    from lens.core.modalities.bootstrap import reset_bootstrap_for_tests

    reset_bootstrap_for_tests()
