from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.address import NarrativeAddress
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, resolve_address, validate_slug
from lens.core.operators.section import SectionOperator
from lens.core.llm import LLMError


app = typer.Typer(no_args_is_help=True)


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
    _section_start(session, narrative, id.strip(), pins=pin, unpins=unpin)


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
    _section_end(session, narrative, llm_id=llm)


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
    _section_range(
        session,
        narrative,
        id=id.strip(),
        address=address,
        start_line=start_line,
        end_line=end_line,
        pins=pin,
        unpins=unpin,
        llm_id=llm,
    )


def _section_start(
    session: ProjectSession,
    narrative: NarrativeNode,
    id: str,
    pins: list[str] | None = None,
    unpins: list[str] | None = None,
) -> None:
    if not id:
        typer.echo("Error: section ID cannot be empty.", err=True)
        raise typer.Exit(1)
    if not validate_slug(id):
        typer.echo(
            f"Error: invalid section ID '{id}' (alphanumeric, underscores, hyphens only)",
            err=True,
        )
        raise typer.Exit(1)

    cursor = narrative.find_cursor()
    cursor_md = cursor.md_path()
    rel = str(cursor_md.relative_to(session.git_root))
    owner = SectionOperator.owner_id(id, rel)
    storage = session.new_storage(owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        op.start(id, pins=pins or [], unpins=unpins or [])
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Started section '{id}'")


def _section_end(
    session: ProjectSession,
    narrative: NarrativeNode,
    llm_id: str | None = None,
) -> None:
    cursor = narrative.find_cursor()
    if not cursor.key_path:
        typer.echo("lens section end: no open section to close (cursor at root)", err=True)
        raise typer.Exit(1)
    key = cursor.key_path[-1]
    parent_key_path = cursor.key_path[:-1]
    parent = NarrativeNode(
        narrative_root=narrative.narrative_root,
        key_path=parent_key_path,
    )
    parent_md = parent.md_path()
    rel = str(parent_md.relative_to(session.git_root))
    owner = SectionOperator.owner_id(key, rel)
    storage = session.new_storage(owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        asyncio.run(op.end(session, llm_id=llm_id, on_token=_print_token))
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


def _section_range(
    session: ProjectSession,
    narrative: NarrativeNode,
    id: str,
    address: str,
    start_line: int,
    end_line: int,
    pins: list[str],
    unpins: list[str],
    llm_id: str | None,
) -> None:
    if not id:
        typer.echo("Error: section ID cannot be empty.", err=True)
        raise typer.Exit(1)
    if not validate_slug(id):
        typer.echo(
            f"Error: invalid section ID '{id}' (alphanumeric, underscores, hyphens only)",
            err=True,
        )
        raise typer.Exit(1)

    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        typer.echo(f"lens section range: invalid address: {e}", err=True)
        raise typer.Exit(1)

    try:
        resolved = resolve_address(addr, session.project_root)
        target_node = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)

    if not target_node.exists():
        typer.echo(f"lens section range: node does not exist: {address}", err=True)
        raise typer.Exit(1)

    target_md = target_node.md_path()
    rel_path = str(target_md.relative_to(session.git_root))
    owner = SectionOperator.owner_id(id, rel_path)
    storage = session.new_storage(owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        asyncio.run(
            op.section_range(
                target_node=target_node,
                id=id,
                start_line=start_line,
                end_line=end_line,
                session=session,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                on_token=_print_token,
            )
        )
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
    typer.echo(f"Sectioned lines {start_line}–{end_line} into '{id}'", err=True)
