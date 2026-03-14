from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from lens.core.commands.stats import get_stats
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()


@router.get("/stats")
def stats(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    result = get_stats(session)
    transaction: dict[str, Any] | None = None
    if result.has_pending:
        storage = session.new_storage(owner=None)
        transaction = {
            "has_pending": True,
            "owner": str(result.pending_owner) if result.pending_owner is not None else None,
            "is_mutation": result.pending_owner is not None and result.pending_owner.operator == "edit",
            "raw_diff": storage.pending_diff(),
        }

    return {
        "active_narrative": session.active_narrative.narrative_root.name
        if session.active_narrative is not None
        else None,
        "narratives": [t[0] for t in result.trees],
        "cursor": str(result.cursor_addr) if result.cursor_addr is not None else None,
        "has_pending": result.has_pending,
        "pending_owner": str(result.pending_owner) if result.pending_owner is not None else None,
        "dataset_name": result.dataset_name,
        "current_datasets": result.current_datasets if result.dataset_name is None else [],
        "kb_types": result.kb_types,
        "kb_count": result.kb_count,
        "effective_pins_at_cursor": result.effective_pins_at_cursor,
        "available_llms": result.available_llms,
        "transaction": transaction,
    }
