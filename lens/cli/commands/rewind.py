"""CLI adapter for ``lens rewind``."""

from __future__ import annotations

import typer

from lens.core.address import NarrativeAddress
from lens.core.commands.rewind import rewind as rewind_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, resolve_address

app = typer.Typer(invoke_without_command=True, no_args_is_help=True, add_completion=False)


@app.callback()
def rewind(
    ctx: typer.Context,
    address: str | None = typer.Argument(
        None,
        help=(
            "Node address to rewind to.  "
            "Use '/' for the narrative root or '/@cursor' for the current cursor."
        ),
    ),
    line: int | None = typer.Argument(
        None,
        help=(
            "Line number within the node (1-based, inclusive).  "
            "When omitted, the cursor is placed at the end of the node."
        ),
    ),
) -> None:
    """Rewind the cursor to a node or line, deleting everything after.

    Without a line number, the cursor is placed at the end of the given node
    (its last closed section).  Everything after that point — later siblings,
    their summaries, close tags, and their child nodes — is deleted.

    With a line number, the node's file is truncated at that line with
    structural adjustments:

    \b
    - Line in front matter        → node is cleared entirely.
    - Line inside an annotation   → annotation and everything after is deleted.
    - Line inside a section body  → the entire section block and child node
                                    are deleted (partial summaries are invalid).
    - Line inside a write body    → body is truncated there and the close tag
                                    is moved to that position.
    - Otherwise (free text)       → simple truncation.

    Side effects such as knowledge-base objects created by design operators
    are never modified.
    """
    if address is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens rewind: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens rewind: no active narrative (run 'lens use <slug>' first)",
            err=True,
        )
        raise typer.Exit(1)

    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        typer.echo(f"lens rewind: invalid address: {e}", err=True)
        raise typer.Exit(1)
    line_arg = line if line is not None else addr.line

    try:
        resolved = resolve_address(addr.node_only(), session.project_root)
        target_node = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"lens rewind: {e}", err=True)
        raise typer.Exit(1)

    if not target_node.exists():
        typer.echo(f"lens rewind: node does not exist: {address}", err=True)
        raise typer.Exit(1)

    storage = session.new_storage()

    try:
        rewind_core(target_node, line_arg, storage)
    except LensException as e:
        typer.echo(f"lens rewind: {e}", err=True)
        raise typer.Exit(1)

    typer.echo("Rewound.")
