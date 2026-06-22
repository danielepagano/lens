from __future__ import annotations

from typing import Literal

import typer

from lens.cli.help_strings import ARG_SLUG_NARRATIVE, CMD_USE, HELP_OPTS
from lens.core.commands.use import use_narrative
from lens.core.exceptions import LensException

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=True,
    add_completion=False,
    help=CMD_USE,
    context_settings={"help_option_names": HELP_OPTS},
)

@app.callback()
def use(
    slug: str = typer.Argument(..., help=ARG_SLUG_NARRATIVE),
    companion: str | None = typer.Option(
        None,
        "--companion",
        help="companion.* KB id for companion chat bootstrap (requires --human)",
    ),
    human: str | None = typer.Option(
        None,
        "--human",
        help="human.* KB id for companion chat bootstrap (requires --companion)",
    ),
) -> None:
    """Select narrative and create folder/_node.md if needed."""
    narrative_kind: Literal["default", "companion_chat"] = "default"
    if companion is not None or human is not None:
        if not companion or not human:
            typer.echo(
                "Error: companion chat requires both --companion (companion.*) and --human (human.*)",
                err=True,
            )
            raise typer.Exit(1)
        narrative_kind = "companion_chat"

    try:
        hint = use_narrative(
            slug,
            narrative_kind=narrative_kind,
            companion_as_kb_id=companion,
            companion_with_kb_id=human,
        )
        typer.echo(f"Using narrative '{slug}'")
        if hint:
            typer.echo(hint)
    except LensException as e:
        if "SLUG" in str(e) or "invalid slug" in str(e):
            typer.echo(f"Error: {e}", err=True)
        else:
            typer.echo(f"lens use: {e}", err=True)
        raise typer.Exit(1)
