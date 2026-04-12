"""Post-operator auto-compress: one entry point for CLI and HTTP after write/play/chat."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from lens.core.compression import (
    Aggressiveness,
    CompressConfig,
    auto_compress_enabled,
    get_last_compress_size,
    get_visible_text,
    measure_visible_bytes,
    should_trigger,
)
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.compress import CompressNoCollate, run_compress
from lens.core.project import ProjectSession

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoCompressCursorState:
    compress_on: bool
    visible_bytes: int
    last_size: int | None
    trigger: Aggressiveness | None


def read_cursor_auto_compress_state(
    session: ProjectSession, narrative: NarrativeNode
) -> AutoCompressCursorState:
    config = CompressConfig.from_project(session.project_root)
    cursor = narrative.find_cursor()
    node_text = cursor.md_path().read_text(encoding="utf-8")
    visible = get_visible_text(node_text)
    current_size = measure_visible_bytes(visible)
    fm = cursor.front_matter()
    on = auto_compress_enabled(config, fm)
    last_size = get_last_compress_size(fm)
    trigger = should_trigger(current_size, last_size, config)
    return AutoCompressCursorState(
        compress_on=on, visible_bytes=current_size, last_size=last_size, trigger=trigger
    )


async def maybe_post_main_auto_compress(
    session: ProjectSession,
    narrative: NarrativeNode,
    *,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
    on_status: Callable[[str], None] | None = None,
    on_info_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> None:
    """After a successful write/play/chat, optionally run compress (same rules everywhere)."""
    try:
        state = read_cursor_auto_compress_state(session, narrative)
        if not state.compress_on or state.trigger is None:
            return
        trigger = state.trigger
        msg = (
            f"node is {state.visible_bytes:,} bytes — auto-compressing ({trigger.value} aggressiveness)…"
        )
        if on_status is not None:
            on_status(msg)
        else:
            _log.info("auto-compress: %s", msg)
        outcome = await run_compress(
            session=session,
            narrative=narrative,
            aggressiveness=trigger,
            on_token=on_token,
            cancel_event=cancel_event,
            no_tool_call_ok=True,
        )
        if outcome is None:
            if on_status is not None:
                on_status("auto-compress interrupted before collate")
            return
        if isinstance(outcome, CompressNoCollate):
            explanation = outcome.explanation
            payload: dict[str, Any] = {
                "type": "info",
                "code": "auto_compress_no_collate",
                "message": explanation,
            }
            if on_info_event is not None:
                await on_info_event(payload)
            elif on_status is not None:
                on_status(f"auto-compress: no collate — {explanation}")
            else:
                _log.info("auto-compress skipped (no tool): %s", explanation)
            return
    except OperatorError as e:
        if on_status is not None:
            on_status(f"auto-compress failed: {e}")
        else:
            _log.warning("auto-compress failed: %s", e)
    except Exception:
        _log.debug("maybe_post_main_auto_compress: unexpected error", exc_info=True)
        if on_status is not None:
            on_status("auto-compress error (see server logs)")


def run_post_main_auto_compress_blocking_cli(
    session: ProjectSession,
    narrative: NarrativeNode,
    *,
    on_token: Callable[[str], Awaitable[None]] | None,
    cancel_event: asyncio.Event | None = None,
    on_status: Callable[[str], None],
) -> None:
    async def _run() -> None:
        async def on_info(payload: dict[str, Any]) -> None:
            msg = str(payload.get("message", ""))
            if msg:
                on_status(f"auto-compress: {msg}")

        await maybe_post_main_auto_compress(
            session,
            narrative,
            on_token=on_token,
            cancel_event=cancel_event,
            on_status=on_status,
            on_info_event=on_info,
        )

    asyncio.run(_run())
