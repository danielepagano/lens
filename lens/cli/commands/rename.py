"""``lens rename`` — rename a narrative node."""

from __future__ import annotations

import typer

from lens.cli.help_strings import ARG_RENAME_ADDR, ARG_NEW_SLUG, CMD_RENAME, HELP_OPTS
from lens.core.commands.rename_node import rename_node
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    no_args_is_help=True,
    help=CMD_RENAME,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback()
def rename(
    address: str = typer.Argument(
        ...,
        help=ARG_RENAME_ADDR,
    ),
    new_slug: str = typer.Argument(
        ...,
        help=ARG_NEW_SLUG,
    ),
) -> None:
    """Rename a narrative node, updating its annotation tag and file/folder name."""
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens rename: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens rename: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    from lens.core.address import NarrativeAddress
    from lens.core.project import resolve_address, unknown_node_hint

    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        typer.echo(f"lens rename: invalid address: {e}", err=True)
        raise typer.Exit(1)

    try:
        resolved = resolve_address(addr, session.project_root)
        node = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"lens rename: {e}", err=True)
        raise typer.Exit(1)

    if not node.exists():
        hint = unknown_node_hint(addr, session.project_root)
        typer.echo(
            f"lens rename: node does not exist: {address}"
            + (f" \u2014 {hint}" if hint else ""),
            err=True,
        )
        raise typer.Exit(1)

    storage = session.new_storage()
    try:
        effective_slug = rename_node(node, new_slug, storage)
    except (ValueError, LensException) as e:
        typer.echo(f"lens rename: {e}", err=True)
        raise typer.Exit(1)

    typer.echo(f"renamed: {address} → {effective_slug}")
