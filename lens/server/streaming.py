"""Shared SSE streaming infrastructure: centralised lock, formatting, response builders."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse


class StreamLock:
    """One-stream-at-a-time guard stored on ``app.state.stream_lock``."""

    def __init__(self) -> None:
        self.kind: str | None = None
        self.cancel_event: asyncio.Event = asyncio.Event()
        self.task: asyncio.Task[None] | None = None

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

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.task is not None and not self.task.done():
            self.task.cancel()


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
) -> AsyncIterator[str]:
    """Yield SSE frames from an operator's event queue.  Releases *lock* on exit."""
    try:
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield sse_message(event)
    finally:
        lock.release()


def operator_stream_response(
    event_queue: asyncio.Queue[dict[str, Any] | None],
    lock: StreamLock,
) -> StreamingResponse:
    return StreamingResponse(
        _operator_sse_gen(event_queue, lock),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
