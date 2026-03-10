from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from lens.core.commands.diff import get_staged_state, get_transaction_state
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()


def _state_to_dict(state: Any) -> dict[str, Any]:
    return {
        "has_pending": state.has_pending,
        "owner": state.owner,
        "is_mutation": state.is_mutation,
        "files": [
            {
                "path": f.path,
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


@router.get("/transaction")
def transaction(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    storage = session.new_storage(owner=None)
    state = get_transaction_state(storage)
    return _state_to_dict(state)


@router.get("/staged")
def staged(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    storage = session.new_storage(owner=None)
    state = get_staged_state(storage)
    return _state_to_dict(state)
