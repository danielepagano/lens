from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from lens.core.commands.stats import get_stats
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()


@router.get("/health")
def health(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    return {"status": "ok"}

@router.get("/stats")
def stats(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    result = get_stats(session)
    return {
        "active_narrative": session.active_narrative.narrative_root.name
        if session.active_narrative is not None
        else None,
        "cursor": str(result.cursor_addr) if result.cursor_addr is not None else None,
        "has_pending": result.has_pending,
        "pending_owner": str(result.pending_owner) if result.pending_owner is not None else None,
        "dataset_name": result.dataset_name,
        "kb_type_count": result.type_count,
        "kb_count": result.kb_count,
    }
