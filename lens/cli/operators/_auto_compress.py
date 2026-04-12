"""Automated compression hooks for write, play, and chat operators."""

from __future__ import annotations

import asyncio
import logging

import typer

from lens.core.compression import (
    AutoCompressMode,
    CompressConfig,
    get_effective_mode,
    get_last_compress_size,
    get_visible_text,
    measure_visible_bytes,
    should_trigger,
)
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.compress import run_compress
from lens.core.project import ProjectSession

_log = logging.getLogger(__name__)


async def _print_token(chunk: str) -> None:
    print(chunk, end="", flush=True)


def check_review_mode(session: ProjectSession, narrative: NarrativeNode) -> bool:
    """Pre-check for ``review`` mode.

    Finds the cursor node, measures visible byte size, and checks whether
    auto-compress would trigger.  If it would, prompts the user via
    ``typer.confirm``.  If they confirm, runs compress and returns ``True``
    (the caller should skip its own operator).  Returns ``False`` in all
    other cases (caller proceeds normally).

    Errors from compress are caught and printed; never raises.
    """
    try:
        config = CompressConfig.from_project(session.project_root)
        cursor = narrative.find_cursor()
        node_text = cursor.md_path().read_text(encoding="utf-8")
        visible = get_visible_text(node_text)
        current_size = measure_visible_bytes(visible)
        fm = cursor.front_matter()
        mode = get_effective_mode(config, fm)
        if mode != AutoCompressMode.REVIEW:
            return False
        last_size = get_last_compress_size(fm)
        aggr = should_trigger(current_size, last_size, config)
        if aggr is None:
            return False
        typer.echo(
            f"\nlens: node is {current_size:,} bytes of visible text "
            f"({aggr.value} aggressiveness) — compress before writing?",
            err=True,
        )
        if not typer.confirm("Run compress now?", default=True, err=True):
            return False
        asyncio.run(
            run_compress(
                session=session,
                narrative=narrative,
                aggressiveness=aggr,
                on_token=_print_token,
            )
        )
        print()
        return True
    except OperatorError as e:
        typer.echo(f"\nlens: auto-compress failed: {e}", err=True)
        return False
    except Exception as e:
        _log.debug("check_review_mode: unexpected error", exc_info=True)
        typer.echo(f"\nlens: auto-compress error: {e}", err=True)
        return False


def run_post_auto_compress(session: ProjectSession, narrative: NarrativeNode) -> None:
    """Post-hook for ``auto`` mode.

    Re-finds the cursor after the main op has written content, measures the
    new size, and triggers compress if warranted.  Errors are caught and
    printed; always non-fatal.
    """
    try:
        config = CompressConfig.from_project(session.project_root)
        cursor = narrative.find_cursor()
        node_text = cursor.md_path().read_text(encoding="utf-8")
        visible = get_visible_text(node_text)
        current_size = measure_visible_bytes(visible)
        fm = cursor.front_matter()
        mode = get_effective_mode(config, fm)
        if mode != AutoCompressMode.AUTO:
            return
        last_size = get_last_compress_size(fm)
        aggr = should_trigger(current_size, last_size, config)
        if aggr is None:
            return
        typer.echo(
            f"\nlens: node is {current_size:,} bytes — auto-compressing "
            f"({aggr.value} aggressiveness)...",
            err=True,
        )
        asyncio.run(
            run_compress(
                session=session,
                narrative=narrative,
                aggressiveness=aggr,
                on_token=_print_token,
            )
        )
        print()
    except OperatorError as e:
        typer.echo(f"\nlens: auto-compress failed: {e}", err=True)
    except Exception as e:
        _log.debug("run_post_auto_compress: unexpected error", exc_info=True)
        typer.echo(f"\nlens: auto-compress error: {e}", err=True)
