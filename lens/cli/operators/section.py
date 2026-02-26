from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from lens.core.address import NarrativeAddress
from lens.core.narrative import NarrativeNode
from lens.core.project import get_active_narrative, require_lens_context, resolve_address, validate_slug
from lens.core.storage import Storage
from lens.core.operators.section import SectionOperator
from lens.core.llm import LLMError


app = typer.Typer(invoke_without_command=True, no_args_is_help=True)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def section(
    id_or_end: str | None = typer.Argument(
        None,
        help="Section ID to start (alphanumeric, underscores, hyphens)",
    ),
    address: str | None = typer.Argument(
        None,
        help="Node address for after-the-fact sectioning",
    ),
    start_line: int | None = typer.Argument(
        None,
        help="First line of range to section (1-based, inclusive)",
    ),
    end_line: int | None = typer.Argument(
        None,
        help="Last line of range to section (1-based, inclusive)",
    ),
    end: bool = typer.Option(
        False,
        "--end",
        "-e",
        help="Close the current section",
    ),
    pin: list[str] = typer.Option(
        [],
        "--pin",
        "-p",
        help="KB ID to pin for this operator (repeatable)",
    ),
    unpin: list[str] = typer.Option(
        [],
        "--unpin",
        "-u",
        help="KB ID to unpin for this operator (repeatable)",
    ),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
) -> None:
    """Start a section at cursor, close the current section, or section a line range.

    \b
    lens section <id>                            start section at cursor
    lens section --end                           close current section
    lens section <id> <address> <start> <end>   section a line range after the fact
    """
    try:
        git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    narrative = get_active_narrative(project_root)
    if narrative is None:
        typer.echo("lens section: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)

    if end:
        _section_end(git_root, project_root, narrative, llm_id=llm)
    elif address is not None or start_line is not None or end_line is not None:
        # After-the-fact range sectioning: all three extra args are required.
        if id_or_end is None or address is None or start_line is None or end_line is None:
            typer.echo(
                "lens section: after-the-fact mode requires: <id> <address> <start_line> <end_line>",
                err=True,
            )
            raise typer.Exit(1)
        _section_range(
            git_root,
            project_root,
            narrative,
            id=id_or_end.strip(),
            address=address,
            start_line=start_line,
            end_line=end_line,
            pins=list(pin),
            unpins=list(unpin),
            llm_id=llm,
        )
    else:
        if id_or_end is None:
            typer.echo("lens section: provide a section ID or use --end / -e", err=True)
            raise typer.Exit(1)
        _section_start(git_root, narrative, id_or_end.strip())


def _section_start(git_root: Path, narrative: NarrativeNode, id: str) -> None:
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
    rel = str(cursor_md.relative_to(git_root))
    owner = SectionOperator.owner_id(id, rel)
    storage = Storage(git_root, owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        op.start(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Started section '{id}'")


def _section_end(
    git_root: Path,
    project_root: Path,
    narrative: NarrativeNode,
    llm_id: str | None = None,
) -> None:
    cursor = narrative.find_cursor()
    if not cursor.key_path:
        typer.echo("lens section --end: no open section to close (cursor at root)", err=True)
        raise typer.Exit(1)
    key = cursor.key_path[-1]
    parent_key_path = cursor.key_path[:-1]
    parent = NarrativeNode(
        narrative_root=narrative.narrative_root,
        key_path=parent_key_path,
    )
    parent_md = parent.md_path()
    rel = str(parent_md.relative_to(git_root))
    owner = SectionOperator.owner_id(key, rel)
    storage = Storage(git_root, owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        asyncio.run(op.end(project_root, llm_id=llm_id, on_token=_print_token))
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


def _section_range(
    git_root: Path,
    project_root: Path,
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
        typer.echo(f"lens section: invalid address: {e}", err=True)
        raise typer.Exit(1)

    try:
        resolved = resolve_address(addr, project_root)
        target_node = resolved.to_node(project_root)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)

    if not target_node.exists():
        typer.echo(f"lens section: node does not exist: {address}", err=True)
        raise typer.Exit(1)

    target_md = target_node.md_path()
    rel_path = str(target_md.relative_to(git_root))
    owner = SectionOperator.owner_id(id, rel_path)
    storage = Storage(git_root, owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        asyncio.run(
            op.section_range(
                target_node=target_node,
                id=id,
                start_line=start_line,
                end_line=end_line,
                project_root=project_root,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                on_token=_print_token,
            )
        )
        print()
    except ValueError as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens section: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens section: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo(f"Sectioned lines {start_line}–{end_line} into '{id}'", err=True)
