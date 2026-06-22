"""CLI adapter for the attach command."""

from __future__ import annotations

import typer

from lens.cli.help_strings import (
    ARG_PATH,
    ARG_MEDIA_ADDR,
    ARG_MEDIA_LINE,
    HELP_OPTS,
    MEDIA_ATTACH,
)
from lens.core.commands.attach import attach as attach_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

attach_app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=True,
    add_completion=False,
    help=MEDIA_ATTACH,
    context_settings={"help_option_names": HELP_OPTS},
)


@attach_app.callback()
def attach_cmd(
    path: str = typer.Argument(
        ..., help=ARG_PATH
    ),
    address: str | None = typer.Argument(
        None,
        help=ARG_MEDIA_ADDR,
    ),
    line: int | None = typer.Argument(
        None,
        help=ARG_MEDIA_LINE,
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Validate only, don't attach"
    ),
) -> None:
    """Attach a media embed after the given line in the given node (defaults: cursor, end of file)."""
    try:
        if not path:
            raise LensException(
                "Usage: lens media attach PATH [ADDRESS] [LINE] [--preview]"
            )

        session = ProjectSession.from_cwd()
        result = attach_core(session, path, preview=preview, address=address, line=line)
        if preview:
            typer.echo(f"{result['path']}  [{result['type']}]")
        else:
            typer.echo(f"attached: {result['embed']}")
    except LensException as e:
        typer.echo(f"lens media attach: {e}", err=True)
        raise typer.Exit(1)
