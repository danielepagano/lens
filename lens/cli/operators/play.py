from __future__ import annotations

import asyncio
from typing import Any

import typer

from lens.cli.options import pin_option, unpin_option  # noqa: F401  # pyright: ignore[reportUnusedImport]  # registers write tool
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.rpg.operators.play import PlayOperator
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True, add_completion=False)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def _play_extra_params(as_pc: str | None, do_pass: bool) -> dict[str, Any] | None:
    ep: dict[str, Any] = {}
    if as_pc is not None:
        ep["as_pc"] = as_pc
    if do_pass:
        ep["pass"] = True
    return ep if ep else None


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
        help="PC key to attribute the prompt to (e.g. alice → [Alice]); must be a pinned pc.*",
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
    do_pass: bool = typer.Option(
        False,
        "--pass",
        help="Have the GM respond now (call the LLM)",
    ),
) -> None:
    """Narrate a player-agency moment in GM voice, then pause for player response.

    Opens a play session sub-node the first time, or continues the current
    session.  Use --module to activate a rules module (e.g. combat, downtime).
    Use --end to close the session.

    By default, play appends only what the player says (no GM / LLM). Use --pass
    when you want the GM to respond. Resolvable @mentions are expanded into an
    HTML comment for later reference.

    Requires at least one player character (KB object tagged 'pc') to be pinned.
    Use -as <key> to attribute the prompt to a specific pinned PC (e.g. -as alice → [Alice]).
    """
    if not end and not retry and not do_pass and not prompt:
        typer.echo(
            "lens play: prompt is required (unless using --end, --retry, or --pass)",
            err=True,
        )
        raise typer.Exit(1)
    if do_pass and retry:
        typer.echo("lens play: --pass cannot be combined with --retry", err=True)
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
                extra_params=_play_extra_params(as_pc, do_pass),
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
