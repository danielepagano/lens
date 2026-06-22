from __future__ import annotations

import typer

from lens.cli.async_cancel import run_with_cancel

from lens.cli.help_strings import (
    ARG_ADDRESS,
    ARG_LINE_1,
    OP_COLLATE,
    OPT_LLM,
    OPT_PIN_SUMMARY,
    OPT_REASONING,
    OPT_SUMMARY_GUIDE,
    OPT_UNPIN_SUMMARY,
    HELP_OPTS,
)
from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
from lens.core.llm import LLMError
from lens.core.operators.collate import CollateOperator


app = typer.Typer(
    no_args_is_help=True,
    help=OP_COLLATE,
    add_completion=False,
    context_settings={"help_option_names": HELP_OPTS},
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _get_session_and_narrative() -> tuple[ProjectSession, NarrativeNode | None]:
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens collate: {e}", err=True)
        raise typer.Exit(1)
    narrative = session.active_narrative
    if narrative is None:
        typer.echo("lens collate: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)
    return session, narrative


@app.callback(invoke_without_command=True)
def collate(
    ctx: typer.Context,
    id: str = typer.Argument(..., help="Section ID for the new child node"),
    address: str = typer.Argument(..., help=ARG_ADDRESS),
    start_line: int = typer.Argument(..., help=ARG_LINE_1),
    end_line: int = typer.Argument(..., help=ARG_LINE_1),
    pin: list[str] = pin_option(OPT_PIN_SUMMARY),
    unpin: list[str] = unpin_option(OPT_UNPIN_SUMMARY),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help=OPT_LLM,
    ),
    reasoning: str | None = typer.Option(
        None,
        "--reasoning",
        help=OPT_REASONING,
    ),
    summary_guide: str | None = typer.Option(
        None,
        "--summary-guide",
        "-g",
        help=OPT_SUMMARY_GUIDE,
    ),
) -> None:
    """Section a line range at an arbitrary address."""
    session, narrative = _get_session_and_narrative()
    assert narrative is not None
    try:
        validate_ids_exist(session.project_root, pin + unpin)
    except LensException as e:
        typer.echo(f"lens collate: {e}", err=True)
        raise typer.Exit(1)
    try:
        _, cancelled = run_with_cancel(
            lambda cancel: CollateOperator.run_collate(
                session=session,
                narrative=narrative,
                id=id.strip(),
                address_str=address,
                start_line=start_line,
                end_line=end_line,
                pins=pin,
                unpins=unpin,
                llm_id=llm,
                reasoning=reasoning,
                on_token=_print_token,
                summary_guidance=(
                    summary_guide.strip()
                    if summary_guide and summary_guide.strip()
                    else None
                ),
                cancel_event=cancel,
            )
        )
        print()
        if cancelled:
            typer.echo("\nlens collate: interrupted", err=True)
            raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"lens collate: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens collate: LLM error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Collated lines {start_line}–{end_line} into '{id.strip()}'", err=True)
