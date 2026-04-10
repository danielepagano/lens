from __future__ import annotations

import asyncio
from typing import Any

import typer

from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.operators.chat import ChatOperator
from lens.core.project import ProjectSession

app = typer.Typer(invoke_without_command=True, add_completion=False)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def chat(
    prompt: str = typer.Argument(
        None,
        help="Stage directions (fresh session) or the character's dialog (inside session)",
    ),
    as_kb_id: str | None = typer.Option(
        None,
        "--as",
        "-as",
        help="KB id of the character the AI will voice (e.g. npc.bob, pc.alice)",
    ),
    with_kb_id: str | None = typer.Option(
        None,
        "--with",
        "-w",
        help="KB id of the counterpart character the user plays (e.g. pc.amy)",
    ),
    pin: list[str] = pin_option("KB ID to pin (repeatable)"),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(None, "--llm", "-l", help="LLM ID to use"),
    reasoning: str | None = typer.Option(
        None, "--reasoning", help="Reasoning override: none, low, medium, high"
    ),
    retry: bool = typer.Option(False, "--retry", "-r", help="Discard and regenerate"),
    end: bool = typer.Option(False, "--end", help="Close the current chat session"),
    slug: str | None = typer.Option(
        None,
        "--slug",
        "-s",
        help="Sub-node id for a new session (default: auto-generated from prompt)",
    ),
) -> None:
    """Have the AI speak as a specific character in the current scene.

    Use --as <kb.id> to specify which character the AI voices.  The character's
    KB object is auto-pinned so it appears in context.

    With --with <kb.id>, opens a session sub-node for a back-and-forth
    conversation.  Inside the session, typing text sends it as the --with
    character and the AI responds as --as.  Omit --as inside a session to
    reuse the last character.

    Use --end to close the session with a prose summary.
    """
    if not end and not retry and not as_kb_id and not prompt:
        typer.echo(
            "lens chat: prompt or --as is required (unless using --end or --retry)",
            err=True,
        )
        raise typer.Exit(1)

    try:
        session = ProjectSession.from_cwd()
    except RuntimeError as e:
        typer.echo(f"lens chat: {e}", err=True)
        raise typer.Exit(1)

    narrative = session.active_narrative
    if narrative is None:
        typer.echo(
            "lens chat: no active narrative (run 'lens use <slug>' first)", err=True
        )
        raise typer.Exit(1)

    # Auto-pin --as and --with characters so they appear in RELEVANT KNOWLEDGE.
    all_pins = list(pin)
    if as_kb_id and as_kb_id not in all_pins:
        all_pins.append(as_kb_id)
    if with_kb_id and with_kb_id not in all_pins:
        all_pins.append(with_kb_id)

    try:
        validate_ids_exist(session.project_root, all_pins + list(unpin))
    except LensException as e:
        typer.echo(f"lens chat: {e}", err=True)
        raise typer.Exit(1)

    extra_params: dict[str, Any] = {}
    if as_kb_id:
        extra_params["as_kb_id"] = as_kb_id
    if with_kb_id:
        extra_params["with_kb_id"] = with_kb_id

    try:
        asyncio.run(
            ChatOperator.run_session(
                session=session,
                narrative=narrative,
                prompt=prompt,
                module_id=None,
                pins=all_pins,
                unpins=list(unpin),
                llm_id=llm,
                reasoning=reasoning,
                retry=retry,
                end=end,
                slug=slug if not end and not retry else None,
                on_token=_print_token,
                on_stream_target=None,
                cancel_event=None,
                extra_params=extra_params,
            )
        )
        print()  # ensure final newline
    except OperatorError as e:
        typer.echo(f"lens chat: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens chat: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        print()
        raise typer.Exit(1)
