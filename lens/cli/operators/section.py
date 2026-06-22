from __future__ import annotations

import asyncio

import typer

from lens.cli.async_cancel import run_with_cancel

from lens.cli.help_strings import (
    OP_SECTION,
    OPT_END_SECTION,
    OPT_LLM_SUMMARY,
    OPT_PIN_SECTION,
    OPT_REASONING,
    OPT_UNPIN_SECTION,
    HELP_OPTS,
)
from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
from lens.core.llm import LLMError
from lens.core.operators.section import SectionOperator


app = typer.Typer(
    no_args_is_help=True,
    help=OP_SECTION,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _get_session_and_narrative() -> tuple[ProjectSession, NarrativeNode | None]:
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    narrative = session.active_narrative
    if narrative is None:
        typer.echo("lens section: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)
    return session, narrative


@app.callback(invoke_without_command=True)
def section(
    ctx: typer.Context,
    id: str | None = typer.Argument(
        None,
        help=(
            "Section ID when starting a section. With --end, optional extra "
            "instructions for the summary LLM (not a section id)."
        ),
    ),
    end: bool = typer.Option(False, "--end", help=OPT_END_SECTION),
    pin: list[str] = pin_option(OPT_PIN_SECTION),
    unpin: list[str] = unpin_option(OPT_UNPIN_SECTION),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help=OPT_LLM_SUMMARY,
    ),
    reasoning: str | None = typer.Option(
        None,
        "--reasoning",
        help=OPT_REASONING,
    ),
) -> None:
    """Create a child node at the cursor and open a section tag."""
    if end:
        guidance = id.strip() if id and id.strip() else None
        _do_end(llm, reasoning, guidance)
        return
    if id and id.strip():
        _do_start(id.strip(), pin, unpin)
        return
    typer.echo(ctx.get_help())
    raise typer.Exit(0)


def _do_start(id: str, pin: list[str], unpin: list[str]) -> None:
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    try:
        validate_ids_exist(session.project_root, pin + unpin)
    except LensException as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    try:
        asyncio.run(SectionOperator.run_start(
            session=session, narrative=narrative, id=id,
            pins=pin, unpins=unpin,
        ))
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Started section '{id}'")


def _do_end(
    llm: str | None,
    reasoning: str | None = None,
    summary_guidance: str | None = None,
) -> None:
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    key: str = ""
    try:
        key, cancelled = run_with_cancel(
            lambda cancel: SectionOperator.run_end(
                session=session,
                narrative=narrative,
                llm_id=llm,
                reasoning=reasoning,
                on_token=_print_token,
                summary_guidance=summary_guidance,
                cancel_event=cancel,
            )
        )
        print()
        if cancelled:
            typer.echo("\nlens section --end: interrupted", err=True)
            raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens section --end: LLM error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Closed section '{key}'", err=True)
