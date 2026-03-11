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


app = typer.Typer(no_args_is_help=True, help="Manage narrative structure into sub-sections.")


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


@app.command()
def start(
    ctx: typer.Context,
    id: str | None = typer.Argument(None, help="Section ID (alphanumeric, underscores, hyphens)"),
    pin: list[str] = pin_option("KB ID to pin in the new section's front matter (repeatable)"),
    unpin: list[str] = unpin_option("KB ID to unpin in the new section's front matter (repeatable)"),
    write: str | None = typer.Option(
        None,
        "--write",
        "-w",
        help="Chain a write operator after section start with this prompt",
    ),
) -> None:
    """Create a child node at the cursor and open a section tag."""
    if not id or not id.strip():
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    try:
        validate_ids_exist(session.project_root, pin + unpin)
    except LensException as e:
        typer.echo(f"lens section start: {e}", err=True)
        raise typer.Exit(1)
    try:
        asyncio.run(SectionOperator.run_start(
            session=session, narrative=narrative, id=id.strip(),
            pins=pin, unpins=unpin, write_prompt=write,
            on_token=_print_token, on_confirm=None,
        ))
        print()
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens section start --write: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens section start --write: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo(f"Started section '{id.strip()}'")


@app.command()
def end(
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
) -> None:
    """Close the current section (appends LLM summary to parent)."""
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    key: str = ""
    try:
        key = asyncio.run(SectionOperator.run_end(
            session=session, narrative=narrative,
            llm_id=llm, on_token=_print_token,
        ))
        print()
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens section end: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens section end: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo(f"Closed section '{key}'", err=True)


@app.command("range")
def _range(  # pyright: ignore[reportUnusedFunction]
    ctx: typer.Context,
    id: str | None = typer.Argument(None, help="Section ID for the new child node"),
    address: str | None = typer.Argument(None, help="Node address to section"),
    start_line: int | None = typer.Argument(None, help="First line of range (1-based, inclusive)"),
    end_line: int | None = typer.Argument(None, help="Last line of range (1-based, inclusive)"),
    pin: list[str] = pin_option("KB ID to pin for summary context (repeatable)"),
    unpin: list[str] = unpin_option("KB ID to unpin for summary context (repeatable)"),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
) -> None:
    """Section a line range after the fact (move content into a new child node)."""
    if id is None or address is None or start_line is None or end_line is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    try:
        validate_ids_exist(session.project_root, pin + unpin)
    except LensException as e:
        typer.echo(f"lens section range: {e}", err=True)
        raise typer.Exit(1)
    try:
        asyncio.run(SectionOperator.run_range(
            session=session, narrative=narrative, id=id.strip(),
            address_str=address, start_line=start_line, end_line=end_line,
            pins=pin, unpins=unpin, llm_id=llm, on_token=_print_token,
        ))
        print()
    except ValueError as e:
        typer.echo(f"lens section range: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens section range: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens section range: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo(f"Sectioned lines {start_line}–{end_line} into '{id.strip()}'", err=True)
