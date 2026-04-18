"""Shared CLI option definitions for operators."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer


def complete_kb_ids(ctx: Any, param: Any, incomplete: str) -> list[Any]:
    from click.shell_completion import CompletionItem

    try:
        root = Path.cwd()
        while root != root.parent:
            if (root / "lens.toml").exists():
                break
            root = root.parent
        else:
            return []
        kb_dir = root / "knowledge"
        if not kb_dir.exists():
            return []
        items: list[Any] = []
        for type_dir in sorted(kb_dir.iterdir()):
            if not type_dir.is_dir():
                continue
            for obj_file in sorted(type_dir.glob("*.md")):
                obj_id = f"{type_dir.name}.{obj_file.stem}"
                if obj_id.startswith(incomplete):
                    items.append(CompletionItem(obj_id))
        return items
    except Exception:
        return []


def _complete_reasoning(ctx: Any, param: Any, incomplete: str) -> list[Any]:
    from click.shell_completion import CompletionItem

    choices = ["none", "low", "medium", "high"]
    return [CompletionItem(c) for c in choices if c.startswith(incomplete)]


def pin_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--pin",
        "-p",
        help=help_override or "KB ID to pin for this operator (repeatable)",
        shell_complete=complete_kb_ids,
    )


def unpin_option(help_override: str | None = None) -> Any:
    return typer.Option(
        [],
        "--unpin",
        "-u",
        help=help_override or "KB ID to unpin for this operator (repeatable)",
        shell_complete=complete_kb_ids,
    )


def reasoning_option(help_override: str | None = None) -> Any:
    return typer.Option(
        None,
        "--reasoning",
        help=help_override or "Reasoning override: none, low, medium, high",
        shell_complete=_complete_reasoning,
    )
