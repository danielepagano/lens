"""Lens CLI entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer

from lens.cli.commands import register_commands
from lens.cli.operators import register_operators
from lens.core.project import (
    find_project_root_if_any,
    get_active_narrative,
    is_dataset_root,
    require_lens_context,
)

_DATASET_ALLOWED = frozenset({"stats", "kb", "prompt", "commit", "rollback", "serve", "dev"})

app = typer.Typer(
    name="lens",
    help="Lens: narrative engine with fractal summarization",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _preflight(ctx: typer.Context) -> None:  # pyright: ignore[reportUnusedFunction]
    sub = ctx.invoked_subcommand
    if sub is None:
        return
    proj_root = find_project_root_if_any()
    if sub in ("init", "use") and proj_root is not None and is_dataset_root(proj_root):
        typer.echo(
            "lens: datasets don't use init/use; create lens.toml with [dataset] by hand",
            err=True,
        )
        raise typer.Exit(1)
    if sub in ("init", "use"):
        return
    try:
        _git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens: {e}", err=True)
        raise typer.Exit(1)
    if is_dataset_root(project_root) and sub not in _DATASET_ALLOWED:
        typer.echo(f"lens: {sub} is not available in dataset mode", err=True)
        raise typer.Exit(1)
    if is_dataset_root(project_root):
        return
    _NO_NARRATIVE_NEEDED = ("kb", "prompt", "pin", "commit", "checkpoint", "refresh", "serve", "dev", "deploy")
    if sub not in _NO_NARRATIVE_NEEDED:
        if get_active_narrative(project_root) is None:
            typer.echo("lens: no active narrative (run 'lens use <slug>' first)", err=True)
            raise typer.Exit(1)


register_commands(app)
register_operators(app)


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
