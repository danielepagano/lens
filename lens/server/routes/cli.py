"""CLI execution over HTTP: stream lens subprocess output via SSE, single run at a time."""

from __future__ import annotations

import asyncio
import json
import queue
import shlex
import subprocess
import sys
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()

_LENS_ARGV = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]

_CLI_BLOCKLIST = frozenset({"init", "dev", "serve"})


def _read_stdout(process: Any, out_queue: queue.Queue[tuple[str, str | int]]) -> None:
    if process.stdout is None:
        return
    for line in iter(process.stdout.readline, ""):
        out_queue.put(("out", line))
    process.stdout.close()


def _read_stderr(process: Any, out_queue: queue.Queue[tuple[str, str | int]]) -> None:
    if process.stderr is None:
        return
    for line in iter(process.stderr.readline, ""):
        out_queue.put(("err", line))
    process.stderr.close()


def _wait_process(process: Any, out_queue: queue.Queue[tuple[str, str | int]]) -> None:
    process.wait()
    out_queue.put(("done", process.returncode if process.returncode is not None else -1))


def _sse_message(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.post("/cli/run")
async def cli_run(
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    body = await request.json()
    command = body.get("command", "")
    argv = shlex.split(command) if isinstance(command, str) else []
    subcommand = argv[0] if argv else ""
    if subcommand in _CLI_BLOCKLIST:
        raise HTTPException(
            status_code=400,
            detail=f"Command '{subcommand}' is not allowed from the web UI",
        )

    app = request.app
    if getattr(app.state, "cli_run", None) is not None:
        raise HTTPException(
            status_code=409,
            detail="CLI run already in progress",
        )

    process = subprocess.Popen(
        [*_LENS_ARGV, *argv],
        cwd=session.project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    app.state.cli_run = process

    out_queue: queue.Queue[tuple[str, str | int]] = queue.Queue()
    threading.Thread(target=_read_stdout, args=(process, out_queue), daemon=True).start()
    threading.Thread(target=_read_stderr, args=(process, out_queue), daemon=True).start()
    threading.Thread(target=_wait_process, args=(process, out_queue), daemon=True).start()

    async def stream() -> AsyncIterator[str]:
        loop = asyncio.get_event_loop()
        try:
            while True:
                kind, payload = await loop.run_in_executor(None, out_queue.get)
                if kind == "done":
                    yield _sse_message({"type": "done", "exit_code": payload})
                    break
                yield _sse_message({"type": kind, "text": payload})
        finally:
            if getattr(app.state, "cli_run", None) is process:
                app.state.cli_run = None
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except Exception:
                    process.kill()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/cli/cancel")
async def cli_cancel(request: Request) -> dict[str, str]:
    app = request.app
    process = getattr(app.state, "cli_run", None)
    if process is None:
        return {"status": "ok", "detail": "no run in progress"}
    if process.poll() is None:
        process.terminate()
    app.state.cli_run = None
    return {"status": "ok", "detail": "cancelled"}
