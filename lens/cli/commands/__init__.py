"""Lens CLI commands. Each module exposes an `app` Typer instance."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from typer import Typer


#: Fallback panel for a module that declares no ``help_panel``.
_DEFAULT_PANEL = "Project"

#: Commands contributed by a dataset extension, which exist only here.
_EXTENSION_PANEL = "Dataset commands"


def _discover_commands() -> Iterator[tuple[str, Typer, str | None, str]]:
    """Every command module: its name, app, dataset gate, and help panel.

    A module opts into a panel with a module-level ``help_panel`` string, the
    same shape as ``required_dataset``. Panels are what keep ``lens --help``
    skimmable at 25-odd commands: without them a reader looking for the
    knowledge store reads past every deploy subcommand to find it. The order the
    panels print in is decided by ``LensGroup`` in :mod:`lens.cli.main`, not by
    registration order.
    """
    for _importer, modname, _ in pkgutil.iter_modules(__path__, __name__ + "."):
        mod = importlib.import_module(modname)
        app = getattr(mod, "app", None)
        if app is not None and isinstance(app, typer.Typer):
            name = modname.split(".")[-1]
            required_dataset: str | None = getattr(mod, "required_dataset", None)
            panel: str = getattr(mod, "help_panel", None) or _DEFAULT_PANEL
            yield name, app, required_dataset, panel


def register_commands(main_app: typer.Typer) -> None:
    from lens.core.project import find_project_root, has_mount_config, get_selected_datasets

    try:
        project_root = find_project_root()
        selected = get_selected_datasets(project_root)
    except RuntimeError:
        project_root = None
        selected = []

    for name, app, required_dataset, panel in _discover_commands():
        if required_dataset is not None and required_dataset not in selected:
            continue
        if name == "media" and (
            project_root is None or not has_mount_config(project_root)
        ):
            continue
        # Single-callback apps (no subcommands) must be registered directly to avoid
        # Typer wrapping them in a command group, which breaks argument/option parsing.
        if not app.registered_commands and app.registered_callback:
            callback = app.registered_callback.callback
            if callback is not None:
                help_text = app.registered_callback.help
                if isinstance(help_text, str):
                    main_app.command(name, help=help_text, rich_help_panel=panel)(callback)
                else:
                    main_app.command(name, rich_help_panel=panel)(callback)
                continue
        main_app.add_typer(app, name=name, rich_help_panel=panel)

    if project_root is not None:
        from lens.core.dataset_extensions import (
            ensure_dataset_extensions,
            get_extension_commands,
        )

        ensure_dataset_extensions(project_root)
        for ext_name, ext_app in get_extension_commands():
            if not ext_app.registered_commands and ext_app.registered_callback:
                callback = ext_app.registered_callback.callback
                if callback is not None:
                    main_app.command(ext_name, rich_help_panel=_EXTENSION_PANEL)(callback)
                    continue
            main_app.add_typer(ext_app, name=ext_name, rich_help_panel=_EXTENSION_PANEL)
