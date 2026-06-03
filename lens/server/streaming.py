"""Shared SSE streaming infrastructure: centralised lock, formatting, response builders."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from lens.core.project import ProjectSession

_log = logging.getLogger(__name__)


class StreamLock:
    """One-stream-at-a-time guard stored on ``app.state.stream_lock``."""

    def __init__(self) -> None:
        self.kind: str | None = None
        self.cancel_event: asyncio.Event = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.workflow: Any | None = None

    # -- lifecycle -----------------------------------------------------

    def acquire(self, kind: str) -> None:
        """Mark a stream as active.  Raises *409* if one is already running."""
        if self.kind is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Stream already in progress: {self.kind}",
            )
        self.kind = kind
        self.cancel_event = asyncio.Event()
        self.task = None

    def release(self) -> None:
        self.kind = None
        self.cancel_event = asyncio.Event()
        self.task = None
        self.workflow = None

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.task is not None and not self.task.done():
            self.task.cancel()


def abort_stream(lock: StreamLock, session: ProjectSession) -> None:
    """Stop the active stream. Completed workflow steps stay in the pending transaction."""
    lock.cancel()
    session.kb.evict_tag_cache()


async def watch_client_disconnect(
    request: Request,
    lock: StreamLock,
    session: ProjectSession | None,
) -> None:
    """Cancel and roll back when the SSE client closes the connection."""
    try:
        while not lock.cancel_event.is_set():
            if await request.is_disconnected():
                _log.info("SSE client disconnected — cancelling active stream")
                if session is not None:
                    abort_stream(lock, session)
                else:
                    lock.cancel()
                return
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        return


# -- SSE helpers -------------------------------------------------------

def sse_message(data: dict[str, Any]) -> str:
    """Format a single SSE ``data:`` frame."""
    return f"data: {json.dumps(data)}\n\n"


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


# -- Operator (in-process) stream --------------------------------------

async def _operator_sse_gen(
    event_queue: asyncio.Queue[dict[str, Any] | None],
    lock: StreamLock,
    request: Request,
    session: ProjectSession | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames from an operator's event queue.  Releases *lock* on exit."""
    watcher = asyncio.create_task(watch_client_disconnect(request, lock, session))
    try:
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield sse_message(event)
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        lock.release()


def operator_stream_response(
    event_queue: asyncio.Queue[dict[str, Any] | None],
    lock: StreamLock,
    request: Request,
    session: ProjectSession | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        _operator_sse_gen(event_queue, lock, request, session),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
