"""Dataset-specific project configuration registry.

Each dataset can register default configuration values.  A project may
override them in ``lens.toml`` under ``[config-<dataset>]``.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path
from typing import Any, cast

from lens.core.dataset_extensions import ensure_dataset_extensions
from lens.core.project import DATASET_PACKAGES, get_selected_datasets

_DATASET_CONFIGS: dict[str, dict[str, Any]] = {}


def register_dataset_config(dataset_name: str, defaults: dict[str, Any]) -> None:
    """Register default configuration for a *dataset_name*.

    Called at module-import time by a dataset's Python package (e.g.
    ``lens/rpg/__init__.py``).  *defaults* is a flat dict of key → value.
    """
    _DATASET_CONFIGS[dataset_name] = defaults


def clear_dataset_configs_for_tests() -> None:
    """Reset the registry (tests only)."""
    _DATASET_CONFIGS.clear()


def get_dataset_configs(project_root: Path) -> dict[str, dict[str, Any]]:
    """Return merged config for every active dataset that has registered defaults.

    The resolution order for each dataset is:

    1. Registered Python defaults (from ``register_dataset_config``).
    2. ``[config-<dataset>]`` section in the project's ``lens.toml``
       (may override some or all registered keys).

    If a dataset is selected but has no registered config, it is omitted
    from the result.
    """
    # Ensure extension-based datasets have been loaded so their
    # module-level ``register_dataset_config`` calls have run.
    ensure_dataset_extensions(project_root)

    # Import DATASET_PACKAGES for any selected datasets (these register
    # config at module level — e.g. ``lens.rpg``).
    selected = get_selected_datasets(project_root)
    for name in selected:
        if name in DATASET_PACKAGES:
            try:
                importlib.import_module(DATASET_PACKAGES[name])
            except ImportError:
                pass

    result: dict[str, dict[str, Any]] = {}
    for name in selected:
        if name in _DATASET_CONFIGS:
            result[name] = dict(_DATASET_CONFIGS[name])

    # Apply overrides from project lens.toml [config-<dataset>] sections.
    lens_toml = project_root / "lens.toml"
    if lens_toml.exists():
        with lens_toml.open("rb") as f:
            config: dict[str, Any] = tomllib.load(f)
        for name in result:
            section_key = f"config-{name}"
            raw_overrides = config.get(section_key, {})
            if isinstance(raw_overrides, dict):
                overrides = cast(dict[str, Any], raw_overrides)
                for key, value in overrides.items():
                    if key in result[name]:
                        result[name][key] = value

    return result


def get_dataset_config(
    project_root: Path, dataset_name: str
) -> dict[str, Any] | None:
    """Return merged config for a single dataset, or ``None``."""
    all_configs = get_dataset_configs(project_root)
    return all_configs.get(dataset_name)
