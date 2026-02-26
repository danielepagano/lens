from __future__ import annotations

import typer

from lens.core.commands.init import init_project
from lens.core.exceptions import LensException

app = typer.Typer(invoke_without_command=True)

@app.callback()
def init() -> None:
    """Initialize a Lens project in the current git repo."""
    try:
        root = init_project()
        typer.echo(f"Initialized Lens project at {root}")
    except LensException as e:
        typer.echo(f"lens init: {e}", err=True)
        raise typer.Exit(1)
