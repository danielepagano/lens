from __future__ import annotations

import typer

from lens.cli.help_strings import CMD_REFRESH, HELP_OPTS, OPT_RESET
from lens.core.commands.refresh import execute_refresh
from lens.core.exceptions import LensException

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_REFRESH,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback()
def refresh(
    reset: bool = typer.Option(
        False,
        "--reset",
        help=OPT_RESET,
    ),
) -> None:
    """Fetch from remote and fast-forward the current branch (no merge commits).

    Fails if the remote is ahead and there are uncommitted changes (unless --reset is given).
    When already up to date with the remote, refresh is a no-op even with local pending work.
    Use --reset to recover when checkpoint or a normal refresh cannot proceed.
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
