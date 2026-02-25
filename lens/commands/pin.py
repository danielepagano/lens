"""Pin/unpin knowledge objects to narrative nodes."""

from __future__ import annotations

from pathlib import Path

import typer

from lens.address import NarrativeAddress
from lens.knowledge import parse_id
from lens.narrative import NarrativeNode
from lens.pinning import pin, remove_pin, remove_unpin, unpin
from lens.project import get_active_narrative, require_lens_context
from lens.storage import Storage

app = typer.Typer(no_args_is_help=True)


def _resolve_node(node_arg: str | None) -> tuple[Path, Path, NarrativeNode]:
    git_root, project_root = require_lens_context(Path.cwd())
    addr = NarrativeAddress.parse(node_arg or "/@cursor")
    if addr.cursor or addr.narrative is None:
        narrative = get_active_narrative(project_root)
        if narrative is None:
            typer.echo("lens pin: no active narrative (run 'lens use <slug>' first)", err=True)
            raise typer.Exit(1)
        if addr.cursor:
            return git_root, project_root, narrative.find_cursor()
        addr = addr.with_narrative(narrative.narrative_root.name)
    return git_root, project_root, addr.to_node(project_root)


def _collect_ids(id: str | None, extra_ids: list[str]) -> list[str]:
    return ([id] if id else []) + list(extra_ids)


def _validate_ids(ids: list[str]) -> None:
    invalid: list[str] = []
    for kid in ids:
        try:
            parse_id(kid)
        except ValueError:
            invalid.append(kid)
    if invalid:
        typer.echo(f"Error: invalid ID(s): {', '.join(invalid)}", err=True)
        raise typer.Exit(1)


@app.command()
def add(
    id: str | None = typer.Argument(None, help="Knowledge object ID (type.key)"),
    node_pos: str | None = typer.Argument(None, help="Target node address (default: /@cursor)"),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help="Additional IDs (repeatable)"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node address"),
) -> None:
    """Add knowledge objects to kb_pin at the target node."""
    all_ids = _collect_ids(id, extra_ids)
    if not all_ids:
        typer.echo("Error: provide at least one knowledge object ID (type.key)", err=True)
        raise typer.Exit(1)
    _validate_ids(all_ids)
    try:
        git_root, _project_root, target = _resolve_node(node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        typer.echo(f"lens pin add: {e}", err=True)
        raise typer.Exit(1)
    storage = Storage(git_root, owner=None)
    pin(target, all_ids, storage)
    typer.echo(f"Pinned {len(all_ids)} object(s) to {target.path_str()}")


@app.command()
def remove(
    id: str | None = typer.Argument(None, help="Knowledge object ID to remove from kb_pin"),
    node_pos: str | None = typer.Argument(None, help="Target node address (default: /@cursor)"),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help="Additional IDs (repeatable)"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node address"),
) -> None:
    """Remove knowledge objects from kb_pin."""
    all_ids = _collect_ids(id, extra_ids)
    if not all_ids:
        typer.echo("Error: provide at least one knowledge object ID (type.key)", err=True)
        raise typer.Exit(1)
    _validate_ids(all_ids)
    try:
        git_root, _project_root, target = _resolve_node(node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        typer.echo(f"lens pin remove: {e}", err=True)
        raise typer.Exit(1)
    storage = Storage(git_root, owner=None)
    remove_pin(target, all_ids, storage)
    typer.echo(f"Removed {len(all_ids)} pin(s) from {target.path_str()}")


@app.command()
def block(
    id: str | None = typer.Argument(None, help="Knowledge object ID to add to kb_unpin"),
    node_pos: str | None = typer.Argument(None, help="Target node address (default: /@cursor)"),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help="Additional IDs (repeatable)"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node address"),
) -> None:
    """Add knowledge objects to kb_unpin (cancel ancestor pins)."""
    all_ids = _collect_ids(id, extra_ids)
    if not all_ids:
        typer.echo("Error: provide at least one knowledge object ID (type.key)", err=True)
        raise typer.Exit(1)
    _validate_ids(all_ids)
    try:
        git_root, _project_root, target = _resolve_node(node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        typer.echo(f"lens pin block: {e}", err=True)
        raise typer.Exit(1)
    storage = Storage(git_root, owner=None)
    unpin(target, all_ids, storage)
    typer.echo(f"Blocked {len(all_ids)} object(s) at {target.path_str()}")


@app.command()
def unblock(
    id: str | None = typer.Argument(None, help="Knowledge object ID to remove from kb_unpin"),
    node_pos: str | None = typer.Argument(None, help="Target node address (default: /@cursor)"),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help="Additional IDs (repeatable)"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node address"),
) -> None:
    """Remove knowledge objects from kb_unpin."""
    all_ids = _collect_ids(id, extra_ids)
    if not all_ids:
        typer.echo("Error: provide at least one knowledge object ID (type.key)", err=True)
        raise typer.Exit(1)
    _validate_ids(all_ids)
    try:
        git_root, _project_root, target = _resolve_node(node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        typer.echo(f"lens pin unblock: {e}", err=True)
        raise typer.Exit(1)
    storage = Storage(git_root, owner=None)
    remove_unpin(target, all_ids, storage)
    typer.echo(f"Unblocked {len(all_ids)} object(s) at {target.path_str()}")
