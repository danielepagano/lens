"""Discard the pending transaction (unstaged changes and untracked files)."""

from __future__ import annotations

from pathlib import Path

import typer

from lens.project import require_lens_context
from lens.storage import Storage

app = typer.Typer(invoke_without_command=True)


@app.callback()
def rollback(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt.",
    ),
) -> None:
    """Discard the pending transaction, reverting all unstaged changes."""
    try:
        git_root, _project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens rollback: {e}", err=True)
        raise typer.Exit(1)

    storage = Storage(git_root)
    if not storage.has_pending():
        typer.echo("No pending transaction to roll back.")
        raise typer.Exit(0)

    owner = storage.detect_pending_owner()
    if owner is not None:
        typer.echo(f"Pending transaction owner: {owner}")
    else:
        typer.echo("Pending transaction owner: (non-operator changes)")

    if not yes:
        typer.confirm("Roll back and discard all unstaged changes?", abort=True)

    storage.rollback()
    typer.echo("Transaction rolled back.")
