from __future__ import annotations

import typer

from lens.cli.help_strings import CMD_INIT, DESC_INIT, HELP_OPTS
from lens.core.commands.init import init_project
from lens.core.exceptions import LensException

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_INIT,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback(help=DESC_INIT)
def init() -> None:
    try:
        root = init_project()
        typer.echo(f"Initialized Lens project at {root}")
    except LensException as e:
        typer.echo(f"lens init: {e}", err=True)
        raise typer.Exit(1)
