from __future__ import annotations

import typer

from lens.core.commands.stats import get_stats
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True)


@app.callback()
def stats(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show pending transaction diff and staged (checkpoint) diff.",
    ),
) -> None:
    """Count knowledge objects and narrative nodes."""
    try:
        session = ProjectSession.from_cwd()
        result = get_stats(session, verbose=verbose)
    except (RuntimeError, LensException) as e:
        typer.echo(f"lens stats: {e}", err=True)
        raise typer.Exit(1)

    if result.dataset_name is not None:
        typer.echo(f"Dataset: {result.dataset_name}")
    typer.echo("Knowledge Store")
    typer.echo(f"  Types: {result.type_count}")
    typer.echo(f"  Objects: {result.kb_count}")
    if result.dataset_name is None:
        typer.echo("Narrative trees:")
        for name, count in result.trees:
            typer.echo(f"  {name} ({count} nodes)")

        if result.cursor_addr is not None:
            typer.echo(f"Active narrative cursor:  {result.cursor_addr}")
        else:
            typer.echo("Active narrative cursor:  (no active narrative)")

    typer.echo(f"Open transaction:         {'yes' if result.has_pending else 'no'}")
    if result.has_pending:
        if result.pending_owner is not None:
            typer.echo(f"Transaction owner:        {result.pending_owner}")
        else:
            typer.echo("Transaction owner:        (non-operator changes)")

    if verbose:
        typer.echo("")
        typer.echo("=== Pending transaction (unstaged + untracked) ===")
        typer.echo(result.pending_diff if result.pending_diff else "(none)")
        typer.echo("=== Pending checkpoint (staged) ===")
        typer.echo(result.staged_diff if result.staged_diff else "(none)")
