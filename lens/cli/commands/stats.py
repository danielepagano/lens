from __future__ import annotations

import typer

from lens.core.commands.stats import get_stats
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True)

@app.callback()
def stats() -> None:
    """Count knowledge objects and narrative nodes."""
    try:
        session = ProjectSession.from_cwd()
        result = get_stats(session)
    except (RuntimeError, LensException) as e:
        typer.echo(f"lens stats: {e}", err=True)
        raise typer.Exit(1)

    typer.echo("Knowledge Store")
    typer.echo(f"  Types: {result.type_count}")
    typer.echo(f"  Objects: {result.kb_count}")
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
