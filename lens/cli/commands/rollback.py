from __future__ import annotations

from pathlib import Path
import typer

from lens.core.commands.rollback import check_rollback_status, execute_rollback
from lens.core.exceptions import LensException

app = typer.Typer(invoke_without_command=True)

@app.callback()
def rollback(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt.",
    ),
) -> None:
    """Discard the pending transaction, reverting all unstaged changes."""
    try:
        status = check_rollback_status(Path.cwd())
    except LensException as e:
        typer.echo(f"lens rollback: {e}", err=True)
        raise typer.Exit(1)

    if not status.has_pending:
        typer.echo("No pending transaction to roll back.")
        raise typer.Exit(0)

    if status.owner is not None:
        typer.echo(f"Pending transaction owner: {status.owner}")
    else:
        typer.echo("Pending transaction owner: (non-operator changes)")

    if status.is_mutation:
        typer.echo(
            "Mutation operator detected — rollback will apply a compensating "
            "transaction (claim tags removed, original text restored)."
        )

    if not yes:
        typer.confirm("Roll back?", abort=True)

    try:
        execute_rollback(Path.cwd())
        if status.is_mutation:
            typer.echo("Compensating transaction applied.")
        else:
            typer.echo("Transaction rolled back.")
    except LensException as e:
        typer.echo(f"lens rollback: {e}", err=True)
        raise typer.Exit(1)
