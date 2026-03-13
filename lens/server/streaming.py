"""Shared SSE streaming infrastructure: centralised lock, formatting, response builders."""

from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse


class StreamLock:
    """One-stream-at-a-time guard stored on ``app.state.stream_lock``."""

    def __init__(self) -> None:
        self.kind: str | None = None
        self.cancel_event: asyncio.Event = asyncio.Event()
        self.process: subprocess.Popen[str] | None = None
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
        self.process = None
        self.task = None

    def release(self) -> None:
        self.kind = None
        self.cancel_event = asyncio.Event()
        self.process = None
        self.task = None

    def cancel(self) -> None:
        self.cancel_event.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
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


# -- CLI subprocess stream ---------------------------------------------

def read_stdout(process: Any, out_queue: queue.Queue[tuple[str, str | int]]) -> None:
    if process.stdout is None:
        return
    for line in iter(process.stdout.readline, ""):
        out_queue.put(("out", line))
    process.stdout.close()


def read_stderr(process: Any, out_queue: queue.Queue[tuple[str, str | int]]) -> None:
    if process.stderr is None:
        return
    for line in iter(process.stderr.readline, ""):
        out_queue.put(("err", line))
    process.stderr.close()


def wait_process(process: Any, out_queue: queue.Queue[tuple[str, str | int]]) -> None:
    process.wait()
    out_queue.put(("done", process.returncode if process.returncode is not None else -1))


def start_process_readers(
    process: subprocess.Popen[str],
) -> queue.Queue[tuple[str, str | int]]:
    """Spawn daemon threads for stdout/stderr/wait and return the shared queue."""
    out_queue: queue.Queue[tuple[str, str | int]] = queue.Queue()
    threading.Thread(target=read_stdout, args=(process, out_queue), daemon=True).start()
    threading.Thread(target=read_stderr, args=(process, out_queue), daemon=True).start()
    threading.Thread(target=wait_process, args=(process, out_queue), daemon=True).start()
    return out_queue


async def cli_sse_stream(
    process: subprocess.Popen[str],
    out_queue: queue.Queue[tuple[str, str | int]],
    lock: StreamLock,
    *,
    on_done: Any | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames from a CLI subprocess.  Releases *lock* on exit."""
    loop = asyncio.get_event_loop()
    try:
        while True:
            kind, payload = await loop.run_in_executor(None, out_queue.get)
            if kind == "done":
                yield sse_message({"type": "done", "exit_code": payload})
                break
            yield sse_message({"type": kind, "text": payload})
    finally:
        if on_done is not None:
            on_done()
        lock.release()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except Exception:
                process.kill()


def cli_stream_response(
    process: subprocess.Popen[str],
    lock: StreamLock,
    *,
    on_done: Any | None = None,
) -> StreamingResponse:
    out_queue = start_process_readers(process)
    return StreamingResponse(
        cli_sse_stream(process, out_queue, lock, on_done=on_done),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


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
