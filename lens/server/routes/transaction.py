from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lens.core.commands.checkpoint import execute_checkpoint
from lens.core.commands.commit import execute_commit
from lens.core.commands.refresh import execute_refresh
from lens.core.commands.rollback import rollback
from lens.core.commands.tx_status import get_tx_status
from lens.core.project import ProjectSession
from lens.core.exceptions import LensException
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")


class CheckpointRequest(BaseModel):
    message: str | None = None
    push: bool | None = None


class RefreshRequest(BaseModel):
    reset: bool | None = None


@router.post("/rollback")
def rollback_route(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    try:
        result = rollback(session)
        if not result.performed:
            return {"status": "ok", "detail": "no pending transaction"}
        s = result.status
        return {
            "status": "ok",
            "detail": "transaction rolled back",
            "owner": str(s.owner) if s.owner is not None else None,
            "is_mutation": s.is_mutation,
        }
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}


@router.post("/commit")
def commit(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    try:
        execute_commit(session)
        return {"status": "ok"}
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}


@router.post("/checkpoint")
def checkpoint(
    body: CheckpointRequest | None,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        message = body.message if body is not None else None
        push = body.push if body is not None and body.push is not None else True
        execute_checkpoint(session, message=message, push=push)
        return {"status": "ok"}
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}


@router.post("/refresh")
def refresh(
    body: RefreshRequest | None,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        reset = body.reset if body is not None and body.reset is not None else False
        result = execute_refresh(session, reset=reset)
        return {
            "status": "ok",
            "entries": [
                {"name": e.name, "status": e.status, "action": e.action, "detail": e.detail}
                for e in result.entries
            ],
            "any_changed": result.any_changed,
        }
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}


@router.get("/tx/status")
def tx_status(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    result = get_tx_status(session)
    return {
        "pending_files": result.pending_files,
        "staged_files": result.staged_files,
        "has_remote": result.has_remote,
        "has_upstream": result.has_upstream,
        "fetch_error": result.fetch_error,
        "incoming": result.incoming,
        "unpushed": result.unpushed,
        "remote_head": result.remote_head,
    }
