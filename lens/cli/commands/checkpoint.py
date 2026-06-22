from __future__ import annotations

import typer

from lens.cli.help_strings import ARG_MESSAGE, CMD_CHECKPOINT, HELP_OPTS, OPT_NO_PUSH
from lens.core.commands.checkpoint import execute_checkpoint
from lens.core.exceptions import LensException

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_CHECKPOINT,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback()
def checkpoint(
    message: str | None = typer.Argument(
        None,
        help=ARG_MESSAGE,
    ),
    no_push: bool = typer.Option(
        False,
        "--no-push",
        help=OPT_NO_PUSH,
    ),
) -> None:
    """Stage all changes, commit, and push if remote is configured."""
    try:
        from lens.core.project import ProjectSession

        session = ProjectSession.from_cwd()
        execute_checkpoint(session, message=message, push=not no_push)
        typer.echo("Checkpoint created.")
    except RuntimeError as e:
        typer.echo(f"lens checkpoint: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens checkpoint: {e}", err=True)
        raise typer.Exit(1)
