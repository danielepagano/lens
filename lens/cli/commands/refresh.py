from __future__ import annotations

import typer

from lens.core.commands.refresh import execute_refresh
from lens.core.exceptions import LensException

app = typer.Typer(invoke_without_command=True, add_completion=False)


@app.callback()
def refresh(
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Match the remote branch exactly: discard unpushed commits, uncommitted work, "
        "and untracked files.",
    ),
) -> None:
    """Fetch from remote and fast-forward the current branch (no merge commits).

    Fails if there are uncommitted changes unless --reset is given. Use --reset to recover when
    checkpoint or a normal refresh cannot proceed.
    """
    try:
        from lens.core.project import ProjectSession

        session = ProjectSession.from_cwd()
        execute_refresh(session, reset=reset)
        typer.echo("Refreshed." if not reset else "Reset to match remote.")
    except RuntimeError as e:
        typer.echo(f"lens refresh: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens refresh: {e}", err=True)
        raise typer.Exit(1)
