from __future__ import annotations

import typer

from lens.core.commands.use import use_narrative
from lens.core.exceptions import LensException

app = typer.Typer(invoke_without_command=True, no_args_is_help=True)

@app.callback()
def use(
    slug: str = typer.Argument(..., help="Narrative slug (alphanumeric, underscores, hyphens)"),
) -> None:
    """Select narrative and create folder/_node.md if needed."""
    try:
        use_narrative(slug)
        typer.echo(f"Using narrative '{slug}'")
    except LensException as e:
        if "SLUG" in str(e) or "invalid slug" in str(e):
            typer.echo(f"Error: {e}", err=True)
        else:
            typer.echo(f"lens use: {e}", err=True)
        raise typer.Exit(1)
