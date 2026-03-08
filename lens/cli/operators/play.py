from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option  # noqa: F401  # pyright: ignore[reportUnusedImport]  # registers write tool
from lens.cli.utils import confirm_tool_call
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.dnd.operators.play import PlayOperator
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def play(
    prompt: str = typer.Argument(
        ...,
        help="Scene direction or situation for the player-facing moment (e.g. what the player says or does)",
    ),
    pin: list[str] = pin_option(
        "KB ID to pin (repeatable); at least one must be tagged 'pc'"
    ),
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
    as_pc: str | None = typer.Option(
        None,
        "--as",
        "-as",
        help="PC key to attribute the prompt to (e.g. alice → [ALICE]); must be a pinned pc.*",
    ),
) -> None:
    """Narrate a player-agency moment in GM voice, then pause for player response.

    Requires at least one player character (KB object tagged 'pc') to be pinned.
    Use -as <key> to attribute the prompt to a specific pinned PC (e.g. -as alice → [ALICE]).
    """
    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens play: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens play: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    try:
        validate_ids_exist(session.project_root, list(pin) + list(unpin))
    except LensException as e:
        typer.echo(f"lens play: {e}", err=True)
        raise typer.Exit(1)

    try:
        asyncio.run(
            PlayOperator.run_inline(
                session=session,
                narrative=narrative,
                prompt=prompt,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                retry=retry,
                on_token=_print_token,
                on_confirm=confirm_tool_call,
                extra_params={"as_pc": as_pc} if as_pc is not None else None,
            )
        )
        print()  # ensure final newline
    except OperatorError as e:
        typer.echo(f"lens play: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens play: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        print()
        raise typer.Exit(1)
