"""CLI execution over HTTP: stream lens subprocess output via SSE, single run at a time."""

from __future__ import annotations

import shlex
import subprocess
import sys
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from lens.core.project import ProjectSession
from lens.server.dependencies import get_session
from lens.server.streaming import StreamLock, cli_stream_response

router = APIRouter()

_LENS_ARGV = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]

_CLI_ALLOWLIST = frozenset(
    {
        "stats",
        "kb",
        "design",
        "dnd",
    }
)

_KB_TAG_MUTATING_SUBS = frozenset({"tag", "delete", "copy", "rename", "extract", "edit"})

_MAX_COMMAND_LEN = 32 * 1024


def _cli_run_may_mutate_tags(argv: list[str]) -> bool:
    if not argv:
        return False
    top = argv[0]
    if top == "kb" and len(argv) > 1:
        return argv[1] in _KB_TAG_MUTATING_SUBS
    return False


def _normalize_cli_argv(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    out: list[str] = [argv[0].lower()]
    for arg in argv[1:]:
        if arg.startswith("--"):
            if "=" in arg:
                key, value = arg.split("=", 1)
                out.append(f"{key.lower()}={value}")
            else:
                out.append(arg.lower())
        elif arg.startswith("-") and len(arg) > 1:
            out.append(f"-{arg[1:].lower()}")
        else:
            out.append(arg)
    return out


@router.post("/cli/run")
async def cli_run(
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    body = await request.json()
    command = body.get("command")
    payload = body.get("payload", "")
    if not isinstance(command, str):
        raise HTTPException(
            status_code=400,
            detail="Request body must include 'command' as a string",
        )
    if not isinstance(payload, str):
        raise HTTPException(
            status_code=400,
            detail="Request body 'payload' must be a string",
        )
    full_len = len(command) + (1 + len(payload) if payload else 0)
    if full_len > _MAX_COMMAND_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Command length must not exceed {_MAX_COMMAND_LEN} characters",
        )
    if command == "" and payload == "":
        argv: list[str] = []
    else:
        argv = [command]
        if payload:
            try:
                argv.extend(shlex.split(payload))
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid payload string: {e}",
                ) from e

    argv = _normalize_cli_argv(argv)
    subcommand = argv[0] if argv else ""
    if subcommand and subcommand not in _CLI_ALLOWLIST:
        raise HTTPException(
            status_code=400,
            detail=f"Command '{subcommand}' is not allowed from the web UI",
        )

    lock: StreamLock = request.app.state.stream_lock
    lock.acquire("cli")

    tag_mutating = _cli_run_may_mutate_tags(argv)

    # No shell: argv is passed as a list so user input cannot inject shell metacharacters.
    process = subprocess.Popen(
        [*_LENS_ARGV, *argv],
        cwd=session.project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    lock.process = process

    def on_done() -> None:
        if tag_mutating:
            session.kb.evict_tag_cache()

    return cli_stream_response(process, lock, on_done=on_done)


@router.post("/cli/cancel")
async def cli_cancel(
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> dict[str, str]:
    lock: StreamLock = request.app.state.stream_lock
    if lock.kind is None:
        return {"status": "ok", "detail": "no run in progress"}
    lock.cancel()
    session.kb.evict_tag_cache()
    return {"status": "ok", "detail": "cancelled"}
