from __future__ import annotations

import typer

from lens.core.commands.commit import execute_commit
from lens.core.exceptions import LensException

app = typer.Typer(invoke_without_command=True)


@app.callback()
def commit() -> None:
    """Stage all changes (git add -A)."""
    try:
        from lens.core.project import ProjectSession

        session = ProjectSession.from_cwd()
        execute_commit(session)
        typer.echo("Staged all changes.")
    except RuntimeError as e:
        typer.echo(f"lens commit: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens commit: {e}", err=True)
        raise typer.Exit(1)
