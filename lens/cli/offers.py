"""CLI side of trigger offers: ask after a turn, and run what was accepted.

An **offer** is a ``<!-- suggest:<slug> -->`` marker in the cursor's passage
whose trigger is still open (see :mod:`lens.core.triggers`).  After any turn that
leaves one, Lens asks ``Run <slug>? [Y/n/e]``; ``e`` edits the stored ``run``
here, inside Lens, so the slug never has to ride on a command line.

Interactive only when both stdin and stdout are terminals.  Anywhere else — a
pipe, a script, a test runner — the offer is printed as a hint naming
``lens trigger <slug>`` instead, so automation never blocks on a prompt.
"""

from __future__ import annotations

import sys
from typing import Any

import typer

from lens.cli.async_cancel import run_with_cancel
from lens.core.exceptions import LensException, OperatorError
from lens.core.project import ProjectSession
from lens.core.triggers import Trigger, TriggerError, fire_trigger, open_offers


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _echo_offer(offer: Trigger) -> None:
    typer.echo(f"\nOffer: {offer.slug} — when {offer.when}", err=True)
    typer.echo(f"  run: {offer.run}", err=True)


def run_trigger_cli(
    session: ProjectSession, slug: str, run: str | None = None, *, who: str = "lens"
) -> bool:
    """Fire *slug* (with an optional edited *run*), streaming tokens. ``False`` on failure."""
    narrative = session.active_narrative
    if narrative is None:
        typer.echo(f"{who}: no active narrative", err=True)
        return False

    def _status(message: str) -> None:
        typer.echo(f"\n{who}: {message}", err=True)

    try:
        result: Any
        result, cancelled = run_with_cancel(
            lambda cancel: fire_trigger(
                session=session,
                narrative=narrative,
                slug=slug,
                run=run,
                on_token=_print_token,
                on_stream_target=None,
                cancel_event=cancel,
                on_status=_status,
            )
        )
    except (TriggerError, OperatorError, LensException) as e:
        typer.echo(f"{who}: {e}", err=True)
        return False
    print()
    if cancelled:
        return False
    _report_kb_result(result)
    return True


def _report_kb_result(result: Any) -> None:
    from lens.core.commands.kb import KbMaterializeResult

    if not isinstance(result, KbMaterializeResult):
        return
    report_offer_errors(result)


def report_offer_errors(result: Any) -> None:
    """Print ``suggest`` ops a session close could not honour."""
    for reason in getattr(result, "offer_errors", []) or []:
        typer.echo(f"not offered: {reason}", err=True)


def offer_after_turn(session: ProjectSession, *, who: str = "lens") -> None:
    """Ask about (or print) every open offer at the cursor, after a turn.

    Loops, because accepting an offer can lead straight to another: a design
    session opened by a trigger ends by offering the play session that runs
    what it built.  A declined slug is not asked about again in this loop; it
    stays an offer, and ``lens trigger`` lists it.
    """
    narrative = session.active_narrative
    if narrative is None:
        return
    declined: set[str] = set()
    while True:
        try:
            offers = [o for o in open_offers(session.kb, narrative) if o.slug not in declined]
        except (OSError, ValueError, LensException):
            return
        if not offers:
            return
        if not is_interactive():
            for offer in offers:
                _echo_offer(offer)
                typer.echo(f"  (run it with 'lens trigger {offer.slug}')", err=True)
            return
        offer = offers[0]
        _echo_offer(offer)
        answer = typer.prompt(
            f"Run {offer.slug}? [Y/n/e]", default="y", show_default=False, err=True
        ).strip().lower()
        if answer in ("n", "no"):
            declined.add(offer.slug)
            continue
        run: str | None = None
        if answer in ("e", "edit"):
            edited = typer.edit(offer.run)
            if edited is None:
                declined.add(offer.slug)
                continue
            run = " ".join(edited.split())
            if not run:
                declined.add(offer.slug)
                continue
        if not run_trigger_cli(session, offer.slug, run, who=who):
            return
