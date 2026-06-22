from __future__ import annotations

import typer

from lens.cli.help_strings import CMD_ROLLBACK, DESC_ROLLBACK, HELP_OPTS
from lens.core.commands.rollback import rollback as rollback_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_ROLLBACK,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback(help=DESC_ROLLBACK)
def rollback() -> None:
    try:
        session = ProjectSession.from_cwd()
        result = rollback_core(session)
    except (RuntimeError, LensException) as e:
        typer.echo(f"lens rollback: {e}", err=True)
        raise typer.Exit(1)

    if not result.performed:
        typer.echo("No pending transaction to roll back.")
        raise typer.Exit(0)

    status = result.status
    if status.owner is not None:
        typer.echo(f"Pending transaction owner: {status.owner}")
    else:
        typer.echo("Pending transaction owner: (non-operator changes)")

    if status.is_mutation:
        typer.echo(
            "Mutation operator detected — rollback will apply a compensating "
            "transaction (claim tags removed, original text restored)."
        )

    if status.is_mutation:
        typer.echo("Compensating transaction applied.")
    else:
        typer.echo("Transaction rolled back.")
