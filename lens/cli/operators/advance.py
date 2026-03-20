from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True, add_completion=False)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def advance(
    days: int = typer.Option(
        1,
        "--days",
        "-d",
        help="Number of days to advance (default: 1)",
    ),
    pin: list[str] = pin_option("KB ID to pin"),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
    retry: bool = typer.Option(
        False,
        "--retry",
        "-r",
        help="Discard generated text and regenerate",
    ),
) -> None:
    """Advance time, update fronts, resolve consequences."""
    from lens.rpg.operators.advance import AdvanceOperator

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
                retry=retry,
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
