"""Lens CLI operators. Each module exposes an `app` Typer instance."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

import typer

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
    for name, app in _discover_operators():
        main_app.add_typer(app, name=name)
