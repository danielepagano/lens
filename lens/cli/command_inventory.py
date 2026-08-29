"""The command surface, read off the live CLI rather than described anywhere.

``lens skill`` tells an agent what it can run here. Writing that list down would
reproduce the exact failure the command exists to avoid: a description that ages
in place while the tool moves. So it is introspected from the Typer app that is
about to handle the invocation — which means it is right by construction, and it
is right about *this* project, since dataset gating has already decided which
operators and extension commands exist by the time it is read.

Lives in the CLI layer because Typer does. Core takes the plain
:class:`~lens.core.commands.skill.CommandEntry` values this produces and never
learns what a click group is.
"""

from __future__ import annotations

import click
import typer

from lens.core.commands.skill import CommandEntry

_SUMMARY_CHARS = 120
"""Long enough for a full first line of help; short enough to stay one row."""


def collect_command_inventory(app: typer.Typer | None = None) -> tuple[CommandEntry, ...]:
    """Every command the running CLI would accept, in ``lens --help`` order.

    Sub-commands come back as names only. A group's own summary plus its
    sub-command names is enough to know something exists and what to reach for;
    the options behind it are `lens <group> <command> --help`, which is always
    current and which no generated listing can beat.
    """
    if app is None:
        from lens.cli.main import app as main_app

        app = main_app
    group = typer.main.get_command(app)
    if not isinstance(group, click.Group):
        return ()
    ctx = click.Context(group, info_name="lens")

    entries: list[CommandEntry] = []
    for name in group.list_commands(ctx):
        command = group.get_command(ctx, name)
        if command is None or command.hidden:
            continue
        subcommands: tuple[str, ...] = ()
        if isinstance(command, click.Group):
            subcommands = tuple(command.list_commands(ctx))
        entries.append(
            CommandEntry(
                name=name,
                summary=command.get_short_help_str(_SUMMARY_CHARS),
                panel=str(getattr(command, "rich_help_panel", "") or ""),
                subcommands=subcommands,
            )
        )
    return tuple(entries)
