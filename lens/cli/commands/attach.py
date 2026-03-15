"""CLI adapter for the attach command."""

from __future__ import annotations

import typer

from lens.core.commands.attach import attach as attach_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True, no_args_is_help=True, add_completion=False, help="Attach a media file at the cursor.")


@app.callback()
def attach_cmd(
    path: str = typer.Argument(..., help="Mount-relative file path"),
    preview: bool = typer.Option(False, "--preview", help="Validate only, don't attach"),
) -> None:
    try:
        if not path:
            raise LensException("Usage: lens attach PATH [--preview]")
        
        session = ProjectSession.from_cwd()
        result = attach_core(session, path, preview=preview)
        if preview:
            typer.echo(f"{result['path']}  [{result['type']}]")
        else:
            typer.echo(f"attached: {result['embed']}")
    except LensException as e:
        typer.echo(f"lens attach: {e}", err=True)
        raise typer.Exit(1)
