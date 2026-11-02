"""CLI adapter for ``lens trigger``: list open offers at the cursor, or run one."""

from __future__ import annotations

import typer

from lens.cli.help_strings import CMD_TRIGGER, DESC_TRIGGER, HELP_OPTS
from lens.cli.offers import offer_after_turn, run_trigger_cli
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession
from lens.core.triggers import open_offers, open_triggers

help_panel = "Operators"

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=CMD_TRIGGER,
    context_settings={"help_option_names": HELP_OPTS},
)


@app.callback(help=DESC_TRIGGER)
def trigger(
    slug: str | None = typer.Argument(
        None, help="Trigger slug to run (e.g. design-cellar). Omit to list offers."
    ),
    edit: bool = typer.Option(
        False, "--edit", "-e", help="Edit the stored run command before running it."
    ),
    show_all: bool = typer.Option(
        False, "--all", help="List every open trigger declared in the KB, not just offers."
    ),
) -> None:
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens trigger: {e}", err=True)
        raise typer.Exit(1)
    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens trigger: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    if slug is None:
        try:
            items = (
                open_triggers(session.kb, narrative)
                if show_all
                else open_offers(session.kb, narrative)
            )
        except LensException as e:
            typer.echo(f"lens trigger: {e}", err=True)
            raise typer.Exit(1)
        if not items:
            typer.echo(
                "No open triggers declared."
                if show_all
                else "No offers at the cursor. ('lens trigger --all' lists every open trigger.)"
            )
            if show_all:
                _report_problems(session)
            return
        for item in items:
            typer.echo(f"{item.slug}  (on {item.declared_on})")
            typer.echo(f"  when: {item.when}")
            typer.echo(f"  run:  {item.run}")
        if show_all:
            _report_problems(session)
        return

    run: str | None = None
    if edit:
        from lens.core.triggers import TriggerError, find_trigger

        try:
            stored = find_trigger(session.kb, slug).run
        except TriggerError as e:
            typer.echo(f"lens trigger: {e}", err=True)
            raise typer.Exit(1)
        edited = typer.edit(stored)
        if edited is None or not edited.strip():
            typer.echo("lens trigger: edit cancelled", err=True)
            raise typer.Exit(1)
        run = " ".join(edited.split())
    if not run_trigger_cli(session, slug, run, who="lens trigger"):
        raise typer.Exit(1)
    offer_after_turn(session, who="lens trigger")


def _report_problems(session: ProjectSession) -> None:
    """Declarations that were skipped: a hand-written mistake must not be silent."""
    from lens.core.triggers import trigger_problems

    problems = trigger_problems(session.kb)
    if not problems:
        return
    typer.echo("")
    typer.echo("Not usable (skipped until fixed):")
    for problem in problems:
        typer.echo(f"  ! {problem}")
