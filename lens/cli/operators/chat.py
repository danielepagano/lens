from __future__ import annotations

import asyncio
from typing import Any

import typer

from lens.cli.async_cancel import run_with_cancel
from lens.cli.help_strings import (
    ARG_PROMPT_CHAT,
    OP_CHAT,
    OPT_AS_CHAT,
    OPT_WITH,
    OPT_PIN,
    OPT_UNPIN,
    OPT_LLM,
    OPT_REASONING,
    OPT_RETRY,
    OPT_END_CHAT,
    OPT_SLUG_CHAT,
    OPT_NARRATE,
    OPT_WAIT,
    HELP_OPTS,
)
from lens.cli.options import pin_option, unpin_option
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.operator_params import chat_invocation_uses_session, prepare_chat_invocation
from lens.core.operators.chat import ChatOperator
from lens.core.project import ProjectSession

app = typer.Typer(
    invoke_without_command=True,
    add_completion=False,
    help=OP_CHAT,
    context_settings={"help_option_names": HELP_OPTS},
)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


@app.callback()
def chat(
    prompt: str = typer.Argument(
        None,
        help=ARG_PROMPT_CHAT,
    ),
    as_kb_id: str | None = typer.Option(
        None,
        "--as",
        "-as",
        help=OPT_AS_CHAT,
    ),
    with_kb_id: str | None = typer.Option(
        None,
        "--with",
        "-w",
        help=OPT_WITH,
    ),
    pin: list[str] = pin_option(OPT_PIN),
    unpin: list[str] = unpin_option(OPT_UNPIN),
    llm: str | None = typer.Option(None, "--llm", "-l", help=OPT_LLM),
    reasoning: str | None = typer.Option(
        None, "--reasoning", help=OPT_REASONING
    ),
    retry: bool = typer.Option(False, "--retry", "-r", help=OPT_RETRY),
    end: bool = typer.Option(False, "--end", help=OPT_END_CHAT),
    slug: str | None = typer.Option(
        None,
        "--slug",
        "-s",
        help=OPT_SLUG_CHAT,
    ),
    narrate: bool = typer.Option(
        False,
        "--narrate",
        help=OPT_NARRATE,
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        help=OPT_WAIT,
    ),
) -> None:
    """Have the AI speak as a specific character in the current scene.

    Use --as <kb.id> to specify which character the AI voices.  Without --with,
    this is a one-shot inline response written directly into the current node.

    With --with <kb.id>, opens a session sub-node for a back-and-forth
    conversation.  Inside the session, typing text sends it as the --with
    character and the AI responds as --as.  Subsequent calls without --with
    inside an open session continue that session automatically.

    In-session only: --narrate formats the line as a plain blockquote (no
    [Character] prefix).  --wait appends without calling the LLM (several waits
    stay one blockquote run in the transcript).

    Use --end to close the session with a prose summary.
    """
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

    extra_params: dict[str, Any] = {}
    if as_kb_id:
        extra_params["as_kb_id"] = as_kb_id
    if with_kb_id:
        extra_params["with_kb_id"] = with_kb_id
    if narrate:
        extra_params["narrate"] = True
    if wait:
        extra_params["wait"] = True

    llm, reasoning, extra_params = prepare_chat_invocation(
        session,
        narrative,
        llm_id=llm,
        reasoning=reasoning,
        extra_params=extra_params,
    )

    if not end and not retry and not extra_params.get("as_kb_id") and not prompt:
        typer.echo(
            "lens chat: prompt or --as is required (unless using --end or --retry)",
            err=True,
        )
        raise typer.Exit(1)

    # --as / --with are passed as session params; crawl adds their KB objects to
    # context without duplicating them in kb_pin (same idea as --as).
    all_pins = list(pin)

    try:
        ids_check = list(all_pins) + list(unpin)
        ak = extra_params.get("as_kb_id")
        wk = extra_params.get("with_kb_id")
        if isinstance(ak, str):
            ids_check.append(ak)
        if isinstance(wk, str):
            ids_check.append(wk)
        validate_ids_exist(session.project_root, ids_check)
    except LensException as e:
        typer.echo(f"lens chat: {e}", err=True)
        raise typer.Exit(1)

    def _on_status(m: str) -> None:
        typer.echo(f"\nlens: {m}", err=True)

    async def _run(cancel: asyncio.Event) -> None:
        on_status = _on_status
        if chat_invocation_uses_session(end=end, extra_params=extra_params):
            await ChatOperator.run_session(
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
                cancel_event=cancel,
                on_status=on_status,
                extra_params=extra_params,
            )
            return
        session_node, _ = ChatOperator.find_active_session(narrative)
        if session_node is not None:
            await ChatOperator.run_session(
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
                cancel_event=cancel,
                on_status=on_status,
                extra_params=extra_params,
            )
            return
        await ChatOperator.run_inline(
            session=session,
            narrative=narrative,
            prompt=prompt,
            pins=all_pins,
            unpins=list(unpin),
            llm_id=llm,
            reasoning=reasoning,
            retry=retry,
            on_token=_print_token,
            cancel_event=cancel,
            on_status=on_status,
            extra_params=extra_params,
        )

    try:
        _, cancelled = run_with_cancel(_run)
        print()  # ensure final newline
        if cancelled:
            raise typer.Exit(1)
    except OperatorError as e:
        typer.echo(f"lens chat: {e}", err=True)
        raise typer.Exit(1)
    except LensException as e:
        typer.echo(f"lens chat: {e}", err=True)
        raise typer.Exit(1)
