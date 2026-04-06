from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
from lens.core.llm import LLMError
from lens.core.operators.section import SectionOperator


app = typer.Typer(
    no_args_is_help=True,
    help="Start or end a section at the cursor.",
    add_completion=False,
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _get_session_and_narrative() -> tuple[ProjectSession, NarrativeNode | None]:
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    narrative = session.active_narrative
    if narrative is None:
        typer.echo("lens section: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)
    return session, narrative


@app.callback(invoke_without_command=True)
def section(
    ctx: typer.Context,
    id: str | None = typer.Argument(None, help="Section ID (start a section at cursor)"),
    end: bool = typer.Option(False, "--end", help="Close the current section"),
    pin: list[str] = pin_option("KB ID to pin in the new section's front matter (repeatable)"),
    unpin: list[str] = unpin_option("KB ID to unpin in the new section's front matter (repeatable)"),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use for summary (overrides project default)",
    ),
    reasoning: str | None = typer.Option(
        None,
        "--reasoning",
        help="Reasoning override: none, low, medium, high",
    ),
) -> None:
    """Create a child node at the cursor and open a section tag."""
    if end and id and id.strip():
        typer.echo("lens section: cannot use --end and section ID together", err=True)
        raise typer.Exit(1)
    if end:
        _do_end(llm, reasoning)
        return
    if id and id.strip():
        _do_start(id.strip(), pin, unpin)
        return
    typer.echo(ctx.get_help())
    raise typer.Exit(0)


def _do_start(id: str, pin: list[str], unpin: list[str]) -> None:
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    try:
        validate_ids_exist(session.project_root, pin + unpin)
    except LensException as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    try:
        asyncio.run(SectionOperator.run_start(
            session=session, narrative=narrative, id=id,
            pins=pin, unpins=unpin,
        ))
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Started section '{id}'")


def _do_end(llm: str | None, reasoning: str | None = None) -> None:
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    key: str = ""
    try:
        key = asyncio.run(SectionOperator.run_end(
            session=session, narrative=narrative,
            llm_id=llm, reasoning=reasoning, on_token=_print_token,
        ))
        print()
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens section --end: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens section --end: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo(f"Closed section '{key}'", err=True)
