"""CLI-only asyncio helpers: wire SIGINT to a shared cancel event for core operators."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


def run_with_cancel(
    coro: Callable[[asyncio.Event], Awaitable[T]],
) -> tuple[T, bool]:
    """Run *coro* with an ``asyncio.Event``; set it on SIGINT (terminal interrupt).

    Returns ``(result, cancelled)``. Core code must not install signal handlers;
    only ``cancel_event`` drives interruption.
    """
    cancelled = False

    async def _run() -> T:
        nonlocal cancelled
        cancel = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _on_sigint() -> None:
            cancel.set()

        try:
            loop.add_signal_handler(signal.SIGINT, _on_sigint)
        except (NotImplementedError, ValueError, RuntimeError):
            pass
        try:
            return await coro(cancel)
        finally:
            cancelled = cancel.is_set()

    return asyncio.run(_run()), cancelled
