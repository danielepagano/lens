"""CLI adapter for ``lens rewind``."""

from __future__ import annotations

import typer

from lens.cli.help_strings import (
    ARG_LINE_NUM,
    ARG_NODE_ADDR,
    CMD_REWIND,
    DESC_REWIND,
    HELP_OPTS,
)
from lens.core.address import NarrativeAddress
from lens.core.commands.rewind import rewind as rewind_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, resolve_address

app = typer.Typer(
    invoke_without_command=True,
    no_args_is_help=True,
    add_completion=False,
    help=CMD_REWIND,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback(help=DESC_REWIND)
def rewind(
    ctx: typer.Context,
    address: str | None = typer.Argument(
        None,
        help=ARG_NODE_ADDR,
    ),
    line: int | None = typer.Argument(
        None,
        help=ARG_LINE_NUM,
    ),
) -> None:
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
