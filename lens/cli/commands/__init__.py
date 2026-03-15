"""Lens CLI commands. Each module exposes an `app` Typer instance."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from typer import Typer


def _discover_commands() -> Iterator[tuple[str, Typer]]:
    for _importer, modname, _ in pkgutil.iter_modules(__path__, __name__ + "."):
        mod = importlib.import_module(modname)
        app = getattr(mod, "app", None)
        if app is not None and isinstance(app, typer.Typer):
            name = modname.split(".")[-1]
            yield name, app


def register_commands(main_app: typer.Typer) -> None:
    from lens.core.project import DATASET_PACKAGES, find_project_root, get_mount_point, get_selected_datasets

    try:
        project_root = find_project_root()
        selected = get_selected_datasets(project_root)
    except RuntimeError:
        project_root = None
        selected = []

    for name, app in _discover_commands():
        if name in DATASET_PACKAGES and name not in selected:
            continue
        if name == "attach" and (project_root is None or get_mount_point(project_root) is None):
            continue
        # Single-callback apps (no subcommands) must be registered directly to avoid
        # Typer wrapping them in a command group, which breaks argument/option parsing.
        if not app.registered_commands and app.registered_callback:
            callback = app.registered_callback.callback
            if callback is not None:
                main_app.command(name)(callback)
                continue
        main_app.add_typer(app, name=name)
