"""Lens CLI operators. Each module exposes an `app` Typer instance."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

import typer

from lens.core.operator import Operator
from lens.core.project import find_project_root, get_selected_datasets
from lens.core.tools import operator_applies_to_session

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typer import Typer


def _get_operator_class_for_name(name: str) -> type[Operator] | None:
    try:
        core_mod = importlib.import_module(f"lens.core.operators.{name}")
    except ImportError:
        return None
    pascal = "".join(p.title() for p in name.replace("-", "_").split("_"))
    op_class = getattr(core_mod, f"{pascal}Operator", None)
    if op_class is not None and isinstance(op_class, type) and issubclass(op_class, Operator):
        return op_class
    for v in vars(core_mod).values():
        if isinstance(v, type) and issubclass(v, Operator) and getattr(v, "name", None):
            return v
    return None


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
        op_class = _get_operator_class_for_name(name)
        limited = list(getattr(op_class, "limited_to_datasets", [])) if op_class else []
        if not operator_applies_to_session(selected, limited):
            continue
        main_app.add_typer(app, name=name, rich_help_panel="Operators")
