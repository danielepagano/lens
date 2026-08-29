from __future__ import annotations

import typer

from lens.cli.help_strings import (
    ARG_VAR_KEY,
    ARG_VAR_VALUE,
    ARG_PARAM_KEY,
    ARG_PARAM_VALUE,
    ARG_SCOPE,
    CMD_PIN,
    HELP_OPTS,
    PIN_KB,
    PIN_VAR,
    PIN_PARAM,
    PIN_KB_ID,
    PIN_NODE,
    PIN_EXTRA_IDS,
    PIN_NODE_OPT,
)
from lens.core.commands.pin import (
    param_set,
    param_unset,
    pin_add,
    pin_block,
    pin_remove,
    pin_scoped,
    pin_unblock,
    var_set,
    var_unset,
)
from lens.core.exceptions import LensException
from lens.core.mentions import MentionKind
from lens.core.project import ProjectSession

help_panel = "Knowledge"

app = typer.Typer(
    no_args_is_help=True,
    help=CMD_PIN,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)

kb_app = typer.Typer(
    no_args_is_help=True,
    help=PIN_KB,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)
var_app = typer.Typer(
    no_args_is_help=True,
    help=PIN_VAR,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)
param_app = typer.Typer(
    no_args_is_help=True,
    help=PIN_PARAM,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)

app.add_typer(kb_app, name="kb")
app.add_typer(var_app, name="var")
app.add_typer(param_app, name="param")


@kb_app.command()
def add(
    id: str | None = typer.Argument(None, help=PIN_KB_ID),
    node_pos: str | None = typer.Argument("/@cursor", help=PIN_NODE),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help=PIN_EXTRA_IDS),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Pin a KB object to a node so the AI includes it in prompt context."""
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
    node_pos: str | None = typer.Argument("/@cursor", help=PIN_NODE),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help=PIN_EXTRA_IDS),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Unpin a KB object so it no longer appears in context at this node."""
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
    node_pos: str | None = typer.Argument("/@cursor", help=PIN_NODE),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help=PIN_EXTRA_IDS),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Suppress an ancestor pin at this node (kb_unpin)."""
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
    node_pos: str | None = typer.Argument("/@cursor", help=PIN_NODE),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help=PIN_EXTRA_IDS),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Restore an ancestor pin previously suppressed at this node."""
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


@kb_app.command()
def mention(
    id: str | None = typer.Argument(None, help="Knowledge object ID to mention here"),
    node_pos: str | None = typer.Argument("/@cursor", help=PIN_NODE),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help=PIN_EXTRA_IDS),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Mention a KB object at this point — in context for one AI turn."""
    _run_scoped("mention", id, node_pos, extra_ids, node_opt)


@kb_app.command()
def include(
    id: str | None = typer.Argument(None, help="Knowledge object ID to include here"),
    node_pos: str | None = typer.Argument("/@cursor", help=PIN_NODE),
    extra_ids: list[str] = typer.Option([], "--id", "-i", help=PIN_EXTRA_IDS),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Include a KB object at this point — in context for the rest of the node."""
    _run_scoped("include", id, node_pos, extra_ids, node_opt)


def _run_scoped(
    kind: MentionKind,
    id: str | None,
    node_pos: str | None,
    extra_ids: list[str],
    node_opt: str | None,
) -> None:
    verb = "Mentioned" if kind == "mention" else "Included"
    try:
        session = ProjectSession.from_cwd()
        count, target_path, applies_now = pin_scoped(
            session, kind, id, node_pos, extra_ids, node_opt
        )
        typer.echo(f"{verb} {count} object(s) at {target_path}")
        if not applies_now:
            typer.echo(
                f"note: {target_path} is not the cursor — "
                f"{kind}s are not inherited, so this takes effect only while "
                "the cursor is in that node",
                err=True,
            )
    except LensException as e:
        if "invalid ID" in str(e) or "provide at least one" in str(e):
            typer.echo(f"Error: {e}", err=True)
        else:
            typer.echo(f"lens pin kb {kind}: {e}", err=True)
        raise typer.Exit(1)


@var_app.command("set")
def var_set_cmd(
    key: str = typer.Argument(..., help=ARG_VAR_KEY),
    value: list[str] = typer.Argument(
        ...,
        help=ARG_VAR_VALUE,
    ),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Set a @var:key value at the target node."""
    try:
        session = ProjectSession.from_cwd()
        _, target_path = var_set(session, key, list(value), "/@cursor", node_opt)
        typer.echo(f"Set var {key!r} on {target_path}")
    except LensException as e:
        typer.echo(f"lens pin var set: {e}", err=True)
        raise typer.Exit(1)


@var_app.command("unset")
def var_unset_cmd(
    key: str = typer.Argument(..., help=ARG_VAR_KEY),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Remove a @var:key value from the target node."""
    try:
        session = ProjectSession.from_cwd()
        _, target_path = var_unset(session, key, "/@cursor", node_opt)
        typer.echo(f"Unset var {key!r} on {target_path}")
    except LensException as e:
        typer.echo(f"lens pin var unset: {e}", err=True)
        raise typer.Exit(1)


@param_app.command("set")
def param_set_cmd(
    scope: str = typer.Argument(..., help=ARG_SCOPE),
    key: str = typer.Argument(..., help=ARG_PARAM_KEY),
    value: list[str] = typer.Argument(
        ...,
        help=ARG_PARAM_VALUE,
    ),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Set an operator parameter (e.g. llm_id, reasoning) for a scope."""
    try:
        session = ProjectSession.from_cwd()
        _, target_path = param_set(session, scope, key, list(value), "/@cursor", node_opt)
        typer.echo(f"Set param {scope}.{key} on {target_path}")
    except LensException as e:
        typer.echo(f"lens pin param set: {e}", err=True)
        raise typer.Exit(1)


@param_app.command("unset")
def param_unset_cmd(
    scope: str = typer.Argument(..., help=ARG_SCOPE),
    key: str = typer.Argument(..., help=ARG_PARAM_KEY),
    node_opt: str | None = typer.Option(None, "--node", "-n", help=PIN_NODE_OPT),
) -> None:
    """Remove an operator parameter from a scope at the target node."""
    try:
        session = ProjectSession.from_cwd()
        _, target_path = param_unset(session, scope, key, "/@cursor", node_opt)
        typer.echo(f"Unset param {scope}.{key} on {target_path}")
    except LensException as e:
        typer.echo(f"lens pin param unset: {e}", err=True)
        raise typer.Exit(1)
