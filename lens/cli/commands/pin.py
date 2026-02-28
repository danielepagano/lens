from __future__ import annotations

import typer

from lens.core.commands.pin import (
    pin_add,
    pin_remove,
    pin_block,
    pin_unblock,
)
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(no_args_is_help=True, help="Pin or unpin knowledge objects for LLM context at narrative nodes.")


@app.command()
def add(
    id: str | None = typer.Argument(None, help="Knowledge object ID (type.key)"),
    node_pos: str | None = typer.Argument(None, help="Target node address (default: /@cursor)"),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help="Additional IDs (repeatable)"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node address"),
) -> None:
    """Add knowledge objects to kb_pin at the target node."""
    try:
        session = ProjectSession.from_cwd()
        count, target_path = pin_add(session, id, node_pos, extra_ids, node_opt)
        typer.echo(f"Pinned {count} object(s) to {target_path}")
    except LensException as e:
        if "invalid ID" in str(e) or "provide at least one" in str(e):
            typer.echo(f"Error: {e}", err=True)
        else:
            typer.echo(f"lens pin add: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def remove(
    id: str | None = typer.Argument(None, help="Knowledge object ID to remove from kb_pin"),
    node_pos: str | None = typer.Argument(None, help="Target node address (default: /@cursor)"),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help="Additional IDs (repeatable)"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node address"),
) -> None:
    """Remove knowledge objects from kb_pin."""
    try:
        session = ProjectSession.from_cwd()
        count, target_path = pin_remove(session, id, node_pos, extra_ids, node_opt)
        typer.echo(f"Removed {count} pin(s) from {target_path}")
    except LensException as e:
        if "invalid ID" in str(e) or "provide at least one" in str(e):
            typer.echo(f"Error: {e}", err=True)
        else:
            typer.echo(f"lens pin remove: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def block(
    id: str | None = typer.Argument(None, help="Knowledge object ID to add to kb_unpin"),
    node_pos: str | None = typer.Argument(None, help="Target node address (default: /@cursor)"),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help="Additional IDs (repeatable)"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node address"),
) -> None:
    """Add knowledge objects to kb_unpin (cancel ancestor pins)."""
    try:
        session = ProjectSession.from_cwd()
        count, target_path = pin_block(session, id, node_pos, extra_ids, node_opt)
        typer.echo(f"Blocked {count} object(s) at {target_path}")
    except LensException as e:
        if "invalid ID" in str(e) or "provide at least one" in str(e):
            typer.echo(f"Error: {e}", err=True)
        else:
            typer.echo(f"lens pin block: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def unblock(
    id: str | None = typer.Argument(None, help="Knowledge object ID to remove from kb_unpin"),
    node_pos: str | None = typer.Argument(None, help="Target node address (default: /@cursor)"),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help="Additional IDs (repeatable)"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node address"),
) -> None:
    """Remove knowledge objects from kb_unpin."""
    try:
        session = ProjectSession.from_cwd()
        count, target_path = pin_unblock(session, id, node_pos, extra_ids, node_opt)
        typer.echo(f"Unblocked {count} object(s) at {target_path}")
    except LensException as e:
        if "invalid ID" in str(e) or "provide at least one" in str(e):
            typer.echo(f"Error: {e}", err=True)
        else:
            typer.echo(f"lens pin unblock: {e}", err=True)
        raise typer.Exit(1)
