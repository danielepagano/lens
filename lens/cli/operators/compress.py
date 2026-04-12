from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.llm import LLMError
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.project import ProjectSession
from lens.core.operators.compress import run_compress


app = typer.Typer(
    no_args_is_help=True,
    help="Use AI to pick a range on the cursor node and collate it into a child section (prompt required).",
    add_completion=False,
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _get_session_and_narrative() -> tuple[ProjectSession, NarrativeNode | None]:
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens compress: {e}", err=True)
        raise typer.Exit(1)
    narrative = session.active_narrative
    if narrative is None:
        typer.echo("lens compress: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)
    return session, narrative


@app.callback(invoke_without_command=True)
def compress(
    ctx: typer.Context,
    prompt: str | None = typer.Argument(
        None,
        metavar="PROMPT",
        help="Describe which part of the target node to move into a new section (required for manual use)",
    ),
    node: str | None = typer.Option(
        None,
        "--node",
        "-n",
        help="Narrative node address (default: cursor, same as lens pin)",
    ),
    pin: list[str] = pin_option("KB ID to pin for collate summary context (repeatable)"),
    unpin: list[str] = unpin_option("KB ID to unpin (repeatable)"),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
    reasoning: str | None = typer.Option(
        None,
        "--reasoning",
        help="Reasoning override: none, low, medium, high",
    ),
    summary_guide: str | None = typer.Option(
        None,
        "--summary-guide",
        "-g",
        help="Optional extra instructions for the collate summary LLM",
    ),
) -> None:
    """Pick a range via AI (compress_collate tool) then collate at the cursor or --node."""
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    try:
        validate_ids_exist(session.project_root, pin + unpin)
    except LensException as e:
        typer.echo(f"lens compress: {e}", err=True)
        raise typer.Exit(1)
    try:
        asyncio.run(
            run_compress(
                session=session,
                narrative=narrative,
                prompt=prompt,
                address=node,
                pins=pin,
                unpins=unpin,
                llm_id=llm,
                reasoning=reasoning,
                summary_guide=summary_guide,
                on_token=_print_token,
            )
        )
        print()
    except OperatorError as e:
        typer.echo(f"lens compress: {e}", err=True)
        raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"lens compress: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens compress: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens compress: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo("Compress finished (collate applied at cursor).", err=True)
