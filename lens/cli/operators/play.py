from __future__ import annotations

import asyncio

import typer

from lens.cli.options import pin_option, unpin_option  # noqa: F401  # pyright: ignore[reportUnusedImport]  # registers write tool
from lens.cli.utils import confirm_tool_call
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.rpg.operators.play import PlayOperator
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True, add_completion=False)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def play(
    prompt: str = typer.Argument(
        None,
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
    module: str | None = typer.Option(
        None,
        "--module",
        "-m",
        help="Rules module to activate (e.g. 'combat' → rules.combat); swaps previous module",
    ),
    end: bool = typer.Option(
        False,
        "--end",
        help="Close the current play session",
    ),
) -> None:
    """Narrate a player-agency moment in GM voice, then pause for player response.

    Opens a play session sub-node the first time, or continues the current
    session.  Use --module to activate a rules module (e.g. combat, downtime).
    Use --end to close the session.

    Requires at least one player character (KB object tagged 'pc') to be pinned.
    Use -as <key> to attribute the prompt to a specific pinned PC (e.g. -as alice → [ALICE]).
    """
    if not end and not retry and not prompt:
        typer.echo("lens play: prompt is required (unless using --end or --retry)", err=True)
        raise typer.Exit(1)

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

    # Validate module id if provided.
    module_id: str | None = None
    if module:
        if module.startswith("rules."):
            module_id = module[len("rules."):]
        else:
            module_id = module
        if not module_id:
            typer.echo("lens play: --module requires a key after 'rules.'", err=True)
            raise typer.Exit(1)

    try:
        validate_ids_exist(session.project_root, list(pin) + list(unpin))
    except LensException as e:
        typer.echo(f"lens play: {e}", err=True)
        raise typer.Exit(1)

    try:
        asyncio.run(
            PlayOperator.run_session(
                session=session,
                narrative=narrative,
                prompt=prompt,
                module_id=module_id,
                pins=list(pin),
                unpins=list(unpin),
                llm_id=llm,
                retry=retry,
                end=end,
                on_token=_print_token,
                on_stream_target=None,
                cancel_event=None,
                extra_params={"as_pc": as_pc} if as_pc is not None else None,
                on_confirm=confirm_tool_call,
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
