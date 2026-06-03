"""Core operator implementations and lookup helpers."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lens.core.operator import Operator


def _operator_class_from_module(mod: ModuleType) -> type[Operator] | None:
    from lens.core.operator import Operator

    name = getattr(mod, "__name__", "").split(".")[-1]
    pascal = "".join(p.title() for p in name.replace("-", "_").split("_"))
    op_class = getattr(mod, f"{pascal}Operator", None)
    if op_class is not None and isinstance(op_class, type) and issubclass(op_class, Operator):
        return op_class
    for v in vars(mod).values():
        if isinstance(v, type) and issubclass(v, Operator) and getattr(v, "name", None):
            return v
    return None


def get_operator_class_for_name(name: str) -> type[Operator] | None:
    """Return the operator class for a CLI operator slug, or ``None`` if unknown."""
    try:
        core_mod = importlib.import_module(f"lens.core.operators.{name}")
        out = _operator_class_from_module(core_mod)
        if out is not None:
            return out
    except ImportError:
        pass
    from lens.core.project import DATASET_PACKAGES

    for _dataset_name, pkg_name in DATASET_PACKAGES.items():
        try:
            dataset_mod = importlib.import_module(f"{pkg_name}.operators.{name}")
            out = _operator_class_from_module(dataset_mod)
            if out is not None:
                return out
        except ImportError:
            continue
    return None
