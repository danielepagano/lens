from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lens.core.commands.checkpoint import execute_checkpoint
from lens.core.commands.commit import execute_commit
from lens.core.commands.refresh import execute_refresh
from lens.core.commands.rollback import rollback
from lens.core.project import ProjectSession
from lens.core.exceptions import LensException
from lens.server.dependencies import get_session

router = APIRouter()


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
        execute_refresh(session, reset=reset)
        return {"status": "ok"}
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}
