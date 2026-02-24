"""Lens CLI entry point."""

from __future__ import annotations

import sys

import typer

from lens.commands import register_commands
from lens.project import find_git_root, find_project_root, get_active_narrative

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
    git_root = find_git_root()
    if git_root is None:
        typer.echo("lens: not in a git repository", err=True)
        raise typer.Exit(1)
    project_root = find_project_root()
    if project_root is None:
        typer.echo("lens: no lens.toml found (run 'lens init' first)", err=True)
        raise typer.Exit(1)
    if sub == "section":
        if get_active_narrative(project_root) is None:
            typer.echo("lens: no active narrative (run 'lens use <slug>' first)", err=True)
            raise typer.Exit(1)


register_commands(app)


def main() -> int:
    app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
