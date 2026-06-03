"""Modality registry bootstrap for CLI and server."""

from __future__ import annotations

from lens.core.modalities.catalog import MARKER_MODALITY_ID, MARKER_MODULE, import_catalog_modules


def ensure_modalities_registered() -> None:
    """Ensure shipped catalog modalities are registered.

    Normal import registers once. After :func:`~lens.core.modalities.registry.clear_registry_for_tests`,
    reload catalog submodules so each module's ``register_modality(...)`` runs again.
    """
    from lens.core.modalities.registry import registered_ids
    import sys

    if MARKER_MODALITY_ID in registered_ids():
        return
    import_catalog_modules(reload=MARKER_MODULE in sys.modules)


def reset_bootstrap_for_tests() -> None:
    """Compatibility no-op (registration state lives in the registry only)."""
