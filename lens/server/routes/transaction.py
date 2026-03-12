from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from lens.core.commands.checkpoint import execute_checkpoint
from lens.core.commands.commit import execute_commit
from lens.core.commands.rollback import check_rollback_status, execute_rollback
from lens.core.commands.diff import get_staged_state
from lens.core.address import NarrativeAddress
from lens.core.project import ProjectSession
from lens.core.exceptions import LensException
from lens.server.dependencies import get_session

router = APIRouter()


def transaction_state_to_dict(state: Any) -> dict[str, Any]:
    return {
        "has_pending": state.has_pending,
        "owner": state.owner,
        "is_mutation": state.is_mutation,
        "files": [
            {
                "path": f.path,
                "address": (
                    str(
                        NarrativeAddress.from_file_and_annotation(
                            f.path,
                        ).node_only(),
                    )
                    if f.path.startswith("narrative/")
                    else None
                ),
                "hunks": [
                    {
                        "old_start": hunk.old_start,
                        "new_start": hunk.new_start,
                        "lines": [
                            {
                                "kind": line.kind,
                                "text": line.text,
                                "is_annotation": line.is_annotation,
                            }
                            for line in hunk.lines
                        ],
                    }
                    for hunk in f.hunks
                ],
            }
            for f in state.files
        ],
    }


@router.get("/staged")
def staged(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    storage = session.new_storage(owner=None)
    state = get_staged_state(storage)
    return transaction_state_to_dict(state)


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
def checkpoint(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    try:
        execute_checkpoint(session)
        return {"status": "ok"}
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}
