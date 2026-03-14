from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lens.core.commands.checkpoint import execute_checkpoint
from lens.core.commands.commit import execute_commit
from lens.core.commands.rollback import check_rollback_status, execute_rollback
from lens.core.project import ProjectSession
from lens.core.exceptions import LensException
from lens.server.dependencies import get_session

router = APIRouter()


class CheckpointRequest(BaseModel):
    message: str | None = None
    push: bool | None = None


@router.post("/rollback")
def rollback(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    try:
        status = check_rollback_status(session)
        if not status.has_pending:
            return {"status": "ok", "detail": "no pending transaction"}
        execute_rollback(session)
        return {
            "status": "ok",
            "detail": "transaction rolled back",
            "owner": str(status.owner) if status.owner is not None else None,
            "is_mutation": status.is_mutation,
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
