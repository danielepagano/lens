from __future__ import annotations

import asyncio
from typing import Any

import typer

from lens.cli.operators._auto_compress import check_review_mode, run_post_auto_compress
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
        help="Stage directions (one-shot or fresh session) or the character's dialog (inside session)",
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
        help="KB id of the counterpart character the user plays (e.g. pc.amy); triggers session mode",
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
        help="Sub-node id for a new session (default: auto-generated from characters and prompt)",
    ),
) -> None:
    """Have the AI speak as a specific character in the current scene.

    Use --as <kb.id> to specify which character the AI voices.  Without --with,
    this is a one-shot inline response written directly into the current node.

    With --with <kb.id>, opens a session sub-node for a back-and-forth
    conversation.  Inside the session, typing text sends it as the --with
    character and the AI responds as --as.  Subsequent calls without --with
    inside an open session continue that session automatically.

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

    # --as / --with are passed as session params; crawl adds their KB objects to
    # context without duplicating them in kb_pin (same idea as --as).
    all_pins = list(pin)

    try:
        ids_check = list(all_pins) + list(unpin)
        if as_kb_id:
            ids_check.append(as_kb_id)
        if with_kb_id:
            ids_check.append(with_kb_id)
        validate_ids_exist(session.project_root, ids_check)
    except LensException as e:
        typer.echo(f"lens chat: {e}", err=True)
        raise typer.Exit(1)

    extra_params: dict[str, Any] = {}
    if as_kb_id:
        extra_params["as_kb_id"] = as_kb_id
    if with_kb_id:
        extra_params["with_kb_id"] = with_kb_id

    if not end and not retry and check_review_mode(session, narrative):
        return

    try:
        if end or with_kb_id is not None:
            # Session mode: end, start, or continue an explicit session.
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
        else:
            # No --with: check whether we are already inside an open session.
            session_node, _ = ChatOperator.find_active_session(narrative)
            if session_node is not None:
                # Continue the open session without re-specifying --with.
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
                        end=False,
                        slug=None,
                        on_token=_print_token,
                        on_stream_target=None,
                        cancel_event=None,
                        extra_params=extra_params,
                    )
                )
            else:
                # One-shot inline: AI responds as --as in the current node.
                asyncio.run(
                    ChatOperator.run_inline(
                        session=session,
                        narrative=narrative,
                        prompt=prompt,
                        pins=all_pins,
                        unpins=list(unpin),
                        llm_id=llm,
                        reasoning=reasoning,
                        retry=retry,
                        on_token=_print_token,
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

    if not end:
        run_post_auto_compress(session, narrative)
