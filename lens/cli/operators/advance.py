from __future__ import annotations

import asyncio

import typer

from lens.cli.help_strings import (
    ARG_FEEDBACK,
    OP_ADVANCE,
    OPT_LLM,
    OPT_REASONING,
    OPT_RETRY,
    OPT_END_ADVANCE,
    OPT_DAYS,
    OPT_PIN,
    OPT_UNPIN,
    HELP_OPTS,
)
from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=OP_ADVANCE,
    context_settings={"help_option_names": HELP_OPTS},
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def advance(
    feedback: str | None = typer.Argument(
        None,
        help=ARG_FEEDBACK,
    ),
    days: int = typer.Option(
        1,
        "--days",
        "-d",
        help=OPT_DAYS,
    ),
    pin: list[str] = pin_option(OPT_PIN),
    unpin: list[str] = unpin_option(OPT_UNPIN),
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
    retry: bool = typer.Option(
        False,
        "--retry",
        "-r",
        help=OPT_RETRY,
    ),
    end: bool = typer.Option(
        False,
        "--end",
        help=OPT_END_ADVANCE,
    ),
) -> None:
    """Advance time, update fronts, resolve consequences."""
    from lens.rpg.operators.advance import AdvanceOperator

    if end and retry:
        typer.echo(
            "lens advance: cannot use --end and --retry together",
            err=True,
        )
        raise typer.Exit(1)
    if not end and days < 1:
        typer.echo("lens advance: days must be >= 1", err=True)
        raise typer.Exit(1)

    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens advance: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens advance: no active narrative (run 'lens use <slug>' first)",
            err=True,
        )
        raise typer.Exit(1)

    try:
        validate_ids_exist(session.project_root, list(pin) + list(unpin))
    except LensException as e:
        typer.echo(f"lens advance: {e}", err=True)
        raise typer.Exit(1)

    try:
        asyncio.run(
            AdvanceOperator.run_advance(
                session=session,
                narrative=narrative,
                increment=days,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                reasoning=reasoning,
                retry=retry,
                feedback=feedback,
                end=end,
                on_token=_print_token,
            )
        )
        print()  # ensure final newline
    except OperatorError as e:
        typer.echo(f"lens advance: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens advance: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        print()
        raise typer.Exit(1)
