"""Load optional Python extensions declared by active datasets."""

from __future__ import annotations

import importlib
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from lens.core.exceptions import LensException
from lens.core.project import get_selected_datasets, resolve_dataset_path

if TYPE_CHECKING:
    from typer import Typer

ExtensionRegisterFn = Callable[..., None]

_EXTENSION_COMMANDS: list[tuple[str, Typer]] = []
_LOADED_DATASETS: set[str] = set()


def read_dataset_extension(dataset_path: Path) -> str | None:
    """Return ``[dataset] extension`` from the dataset's ``lens.toml``, or ``None``."""
    lens_toml = dataset_path / "lens.toml"
    if not lens_toml.is_file():
        return None
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_dataset = config.get("dataset", {})
    dataset: dict[str, Any] = (
        cast(dict[str, Any], raw_dataset) if isinstance(raw_dataset, dict) else {}
    )
    raw_ext = dataset.get("extension")
    if not isinstance(raw_ext, str):
        return None
    ext = raw_ext.strip()
    return ext if ext else None


def _parse_extension_spec(spec: str) -> tuple[str, str | None]:
    """Split ``module`` or ``module:callable``."""
    if ":" in spec:
        module_name, callable_name = spec.split(":", 1)
        return module_name.strip(), callable_name.strip() or None
    return spec.strip(), None


def _ensure_dataset_root_on_path(dataset_path: Path) -> None:
    root = str(dataset_path.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def _invoke_extension(
    spec: str,
    *,
    dataset_name: str,
    dataset_path: Path,
    project_root: Path,
) -> None:
    module_name, callable_name = _parse_extension_spec(spec)
    if not module_name:
        raise LensException(f"dataset '{dataset_name}': empty extension spec")

    _ensure_dataset_root_on_path(dataset_path)
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise LensException(
            f"dataset '{dataset_name}': failed to import extension '{module_name}': {e}"
        ) from e

    if callable_name:
        target = getattr(module, callable_name, None)
        if target is None or not callable(target):
            raise LensException(
                f"dataset '{dataset_name}': extension '{callable_name}' not found "
                f"in module '{module_name}'"
            )
        register_fn = cast(ExtensionRegisterFn, target)
        register_fn(
            dataset_name=dataset_name,
            dataset_path=dataset_path,
            project_root=project_root,
        )
    else:
        register_fn = getattr(module, "register", None)
        if register_fn is not None and callable(register_fn):
            register_fn(
                dataset_name=dataset_name,
                dataset_path=dataset_path,
                project_root=project_root,
            )


def register_extension_command(name: str, app: Typer) -> None:
    """Register a Typer sub-app exposed as ``lens <name>``."""
    for existing_name, _ in _EXTENSION_COMMANDS:
        if existing_name == name:
            return
    _EXTENSION_COMMANDS.append((name, app))


def get_extension_commands() -> list[tuple[str, Typer]]:
    return list(_EXTENSION_COMMANDS)


def clear_extension_state_for_tests() -> None:
    """Reset extension registry (tests only)."""
    _EXTENSION_COMMANDS.clear()
    _LOADED_DATASETS.clear()


def ensure_dataset_extensions(project_root: Path) -> None:
    """Import extensions for each selected dataset that declares one."""
    for dataset_name in get_selected_datasets(project_root):
        if dataset_name in _LOADED_DATASETS:
            continue
        dataset_path = resolve_dataset_path(project_root, dataset_name)
        if dataset_path is None:
            continue
        spec = read_dataset_extension(dataset_path)
        if spec is None:
            _LOADED_DATASETS.add(dataset_name)
            continue
        _invoke_extension(
            spec,
            dataset_name=dataset_name,
            dataset_path=dataset_path,
            project_root=project_root,
        )
        _LOADED_DATASETS.add(dataset_name)


def try_load_dataset_extension(
    project_root: Path,
    dataset_name: str,
    dataset_path: Path,
) -> str | None:
    """Attempt to load one dataset extension; return error message or ``None`` on success."""
    spec = read_dataset_extension(dataset_path)
    if spec is None:
        return None
    try:
        _invoke_extension(
            spec,
            dataset_name=dataset_name,
            dataset_path=dataset_path,
            project_root=project_root,
        )
        return None
    except LensException as e:
        return str(e)
    except Exception as e:
        return f"dataset '{dataset_name}': extension load failed: {e}"
