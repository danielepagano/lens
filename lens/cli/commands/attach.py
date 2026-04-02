"""CLI adapter for the attach command."""

from __future__ import annotations

import typer

from lens.core.commands.attach import attach as attach_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=True,
    add_completion=False,
    help="Attach a media file into the narrative after a line (or at end of node).",
)


@app.callback()
def attach_cmd(
    path: str = typer.Argument(..., help="Mount-relative file path (e.g. 'photo.jpg', not a filesystem path)"),
    address: str | None = typer.Argument(
        None,
        help="Narrative node address (default: /@cursor). Use e.g. '/' or '/chapter-1'.",
    ),
    line: int | None = typer.Argument(
        None,
        help="1-based line to insert after (default: append after last line of the node).",
    ),
    preview: bool = typer.Option(False, "--preview", help="Validate only, don't attach"),
) -> None:
    """Attach a media embed after the given line in the given node (defaults: cursor, end of file)."""
    try:
        if not path:
            raise LensException("Usage: lens attach PATH [ADDRESS] [LINE] [--preview]")

        session = ProjectSession.from_cwd()
        result = attach_core(session, path, preview=preview, address=address, line=line)
        if preview:
            typer.echo(f"{result['path']}  [{result['type']}]")
        else:
            typer.echo(f"attached: {result['embed']}")
    except LensException as e:
        typer.echo(f"lens attach: {e}", err=True)
        raise typer.Exit(1)
