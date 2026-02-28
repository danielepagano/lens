"""Lens CLI entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer

from lens.cli.commands import register_commands
from lens.cli.operators import register_operators
from lens.core.project import get_active_narrative, require_lens_context

app = typer.Typer(
    name="lens",
    help="Lens: narrative engine with fractal summarization",
    no_args_is_help=True,
)


@app.callback(invoke_without_command=True)
def _preflight(ctx: typer.Context) -> None:  # pyright: ignore[reportUnusedFunction]
    sub = ctx.invoked_subcommand
    if sub in (None, "init", "use"):
        return
    try:
        _git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens: {e}", err=True)
        raise typer.Exit(1)
    _NO_NARRATIVE_NEEDED = ("init", "use", "kb", "pin", "commit", "checkpoint")
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
