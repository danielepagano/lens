"""Shipped modality implementations.

Each module calls :func:`~lens.core.modalities.registry.register_modality` at
import time. :func:`import_catalog_modules` loads (or reloads) submodules;
:func:`~lens.core.modalities.bootstrap.ensure_modalities_registered` reloads
after :func:`~lens.core.modalities.registry.clear_registry_for_tests` when the
catalog was imported earlier in the process.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

MARKER_MODALITY_ID = "markdown_fragment"
MARKER_MODULE = "lens.core.modalities.catalog.markdown_fragment"


def import_catalog_modules(*, reload: bool = False) -> None:
    """Import or reload every catalog submodule (re-runs module-level registration)."""
    package = __name__
    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        if name.startswith("_"):
            continue
        full_name = f"{package}.{name}"
        if reload and full_name in sys.modules:
            importlib.reload(sys.modules[full_name])
        else:
            importlib.import_module(full_name)


import_catalog_modules()
