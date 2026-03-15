from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
from lens.core.llm import LLMError
from lens.core.operators.collate import CollateOperator


app = typer.Typer(
    no_args_is_help=True,
    help="Section a line range at an arbitrary address (move content into a new child node).",
    add_completion=False,
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _get_session_and_narrative() -> tuple[ProjectSession, NarrativeNode | None]:
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens collate: {e}", err=True)
        raise typer.Exit(1)
    narrative = session.active_narrative
    if narrative is None:
        typer.echo("lens collate: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)
    return session, narrative


@app.callback(invoke_without_command=True)
def collate(
    ctx: typer.Context,
    id: str = typer.Argument(..., help="Section ID for the new child node"),
    address: str = typer.Argument(..., help="Node address to section"),
    start_line: int = typer.Argument(..., help="First line of range (1-based, inclusive)"),
    end_line: int = typer.Argument(..., help="Last line of range (1-based, inclusive)"),
    pin: list[str] = pin_option("KB ID to pin for summary context (repeatable)"),
    unpin: list[str] = unpin_option("KB ID to unpin for summary context (repeatable)"),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
) -> None:
    """Section a line range at an arbitrary address."""
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    try:
        validate_ids_exist(session.project_root, pin + unpin)
    except LensException as e:
        typer.echo(f"lens collate: {e}", err=True)
        raise typer.Exit(1)
    try:
        asyncio.run(CollateOperator.run_collate(
            session=session,
            narrative=narrative,
            id=id.strip(),
            address_str=address,
            start_line=start_line,
            end_line=end_line,
            pins=pin,
            unpins=unpin,
            llm_id=llm,
            on_token=_print_token,
        ))
        print()
    except ValueError as e:
        typer.echo(f"lens collate: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens collate: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens collate: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo(f"Collated lines {start_line}–{end_line} into '{id.strip()}'", err=True)
