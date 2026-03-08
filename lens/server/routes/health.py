from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from lens.core.commands.stats import get_stats
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()


def _serialize_stats(session: ProjectSession) -> dict[str, Any]:
    result = get_stats(session)
    return {
        "kb_type_count": result.type_count,
        "kb_count": result.kb_count,
        "trees": [{"name": name, "node_count": count} for name, count in result.trees],
        "cursor": str(result.cursor_addr) if result.cursor_addr is not None else None,
        "has_pending": result.has_pending,
        "pending_owner": str(result.pending_owner) if result.pending_owner is not None else None,
        "dataset_name": result.dataset_name,
    }


@router.get("/health")
def health(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    return {"status": "ok", "stats": _serialize_stats(session)}
