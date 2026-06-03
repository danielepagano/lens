"""Lens CLI operators. Each module exposes an `app` Typer instance."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

import typer

from lens.core.operators import get_operator_class_for_name
from lens.core.project import find_project_root, get_selected_datasets, operator_applies_to_session

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typer import Typer


def _discover_operators() -> Iterator[tuple[str, Typer]]:
    for _importer, modname, _ in pkgutil.iter_modules(__path__, __name__ + "."):
        mod = importlib.import_module(modname)
        app = getattr(mod, "app", None)
        if app is not None and isinstance(app, typer.Typer):
            name = modname.split(".")[-1]
            yield name, app


def register_operators(main_app: typer.Typer) -> None:
    try:
        project_root = find_project_root()
        selected = get_selected_datasets(project_root)
    except RuntimeError:
        selected = []

    for name, app in _discover_operators():
        op_class = get_operator_class_for_name(name)
        limited = list(getattr(op_class, "limited_to_datasets", [])) if op_class else []
        if not operator_applies_to_session(selected, limited):
            continue
        if not app.registered_commands and app.registered_callback:
            mod = importlib.import_module(f"lens.cli.operators.{name}")
            callback = getattr(mod, name)
            main_app.command(name, rich_help_panel="Operators")(callback)
        else:
            main_app.add_typer(app, name=name, rich_help_panel="Operators")
