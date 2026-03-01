"""Chain specification for operator chaining.

When an operator completes, it can chain to another operator via the ``chain``
argument. Chained operators share the same storage transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast


@dataclass(slots=True)
class ChainSpec:
    """Represents a chained operator to run after the current one."""

    name: str
    id: str | None
    arguments: dict[str, Any]

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ChainSpec | None:
        """Parse a ChainSpec from a dict (e.g. from JSON tool call args)."""
        if not d:
            return None
        name = d.get("name")
        if not name or not isinstance(name, str):
            return None
        raw_args = d.get("arguments")
        if not isinstance(raw_args, dict):
            args: dict[str, Any] = {}
        else:
            args = cast(dict[str, Any], dict(raw_args))  # pyright: ignore[reportUnknownArgumentType]
        return cls(
            name=name,
            id=d.get("id") if isinstance(d.get("id"), str) else None,
            arguments=args,
        )
