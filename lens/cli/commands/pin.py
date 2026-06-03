from __future__ import annotations

import typer

from lens.core.commands.pin import (
    param_set,
    param_unset,
    pin_add,
    pin_block,
    pin_remove,
    pin_unblock,
    var_set,
    var_unset,
)
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(
    no_args_is_help=True,
    help="Pin knowledge, narrative vars, or operator params at narrative nodes.",
    add_completion=False,
)

kb_app = typer.Typer(
    no_args_is_help=True,
    help="Pin or unpin knowledge objects (kb_pin / kb_unpin).",
    add_completion=False,
)
var_app = typer.Typer(
    no_args_is_help=True,
    help="Set or unset vars: in node front matter (string substitution / @var:).",
    add_completion=False,
)
param_app = typer.Typer(
    no_args_is_help=True,
    help="Set or unset operator params under params.global or params.<operator>.",
    add_completion=False,
)

app.add_typer(kb_app, name="kb")
app.add_typer(var_app, name="var")
app.add_typer(param_app, name="param")


@kb_app.command()
def add(
    id: str | None = typer.Argument(None, help="Knowledge object ID (type.key)"),
    node_pos: str | None = typer.Argument("/@cursor", help="Target node address (default: cursor)"),
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
            typer.echo(f"lens pin kb add: {e}", err=True)
        raise typer.Exit(1)


@kb_app.command()
def remove(
    id: str | None = typer.Argument(None, help="Knowledge object ID to remove from kb_pin"),
    node_pos: str | None = typer.Argument("/@cursor", help="Target node address (default: cursor)"),
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
            typer.echo(f"lens pin kb remove: {e}", err=True)
        raise typer.Exit(1)


@kb_app.command()
def block(
    id: str | None = typer.Argument(None, help="Knowledge object ID to add to kb_unpin"),
    node_pos: str | None = typer.Argument("/@cursor", help="Target node address (default: cursor)"),
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
            typer.echo(f"lens pin kb block: {e}", err=True)
        raise typer.Exit(1)


@kb_app.command()
def unblock(
    id: str | None = typer.Argument(None, help="Knowledge object ID to remove from kb_unpin"),
    node_pos: str | None = typer.Argument("/@cursor", help="Target node address (default: cursor)"),
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
            typer.echo(f"lens pin kb unblock: {e}", err=True)
        raise typer.Exit(1)


@var_app.command("set")
def var_set_cmd(
    key: str = typer.Argument(..., help="Var key"),
    value: list[str] = typer.Argument(
        ...,
        help="Value (multiple words join with spaces)",
    ),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node (default: cursor)"),
) -> None:
    """Set a var in front matter at the target node."""
    try:
        session = ProjectSession.from_cwd()
        _, target_path = var_set(session, key, list(value), "/@cursor", node_opt)
        typer.echo(f"Set var {key!r} on {target_path}")
    except LensException as e:
        typer.echo(f"lens pin var set: {e}", err=True)
        raise typer.Exit(1)


@var_app.command("unset")
def var_unset_cmd(
    key: str = typer.Argument(..., help="Var key"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node (default: cursor)"),
) -> None:
    """Remove a var from front matter at the target node."""
    try:
        session = ProjectSession.from_cwd()
        _, target_path = var_unset(session, key, "/@cursor", node_opt)
        typer.echo(f"Unset var {key!r} on {target_path}")
    except LensException as e:
        typer.echo(f"lens pin var unset: {e}", err=True)
        raise typer.Exit(1)


@param_app.command("set")
def param_set_cmd(
    scope: str = typer.Argument(..., help="'global' or operator slug (e.g. write)"),
    key: str = typer.Argument(..., help="Canonical param name (e.g. llm_id)"),
    value: list[str] = typer.Argument(
        ...,
        help="Value (booleans/numbers coerced; multiple words join with spaces)",
    ),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node (default: cursor)"),
) -> None:
    """Set a param under params.<scope> at the target node."""
    try:
        session = ProjectSession.from_cwd()
        _, target_path = param_set(session, scope, key, list(value), "/@cursor", node_opt)
        typer.echo(f"Set param {scope}.{key} on {target_path}")
    except LensException as e:
        typer.echo(f"lens pin param set: {e}", err=True)
        raise typer.Exit(1)


@param_app.command("unset")
def param_unset_cmd(
    scope: str = typer.Argument(..., help="'global' or operator slug"),
    key: str = typer.Argument(..., help="Param key to remove"),
    node_opt: str | None = typer.Option(None, "--node", "-n", help="Target node (default: cursor)"),
) -> None:
    """Remove a param key from params.<scope> at the target node."""
    try:
        session = ProjectSession.from_cwd()
        _, target_path = param_unset(session, scope, key, "/@cursor", node_opt)
        typer.echo(f"Unset param {scope}.{key} on {target_path}")
    except LensException as e:
        typer.echo(f"lens pin param unset: {e}", err=True)
        raise typer.Exit(1)
