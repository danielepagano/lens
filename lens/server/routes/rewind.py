from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lens.core.address import NarrativeAddress
from lens.core.commands.rewind import rewind_to_line, rewind_to_node
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, resolve_address
from lens.server.dependencies import get_session

router = APIRouter()


class RewindRequest(BaseModel):
    address: str
    line: int | None = None


@router.post("/narrative/rewind")
def narrative_rewind(
    body: RewindRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    narrative = session.active_narrative
    if narrative is None:
        raise HTTPException(
            status_code=400,
            detail="no active narrative (run 'lens use <slug>' first)",
        )

    try:
        addr = NarrativeAddress.parse(body.address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid address: {e}")

    try:
        resolved = resolve_address(addr, session.project_root)
        target_node = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not target_node.exists():
        raise HTTPException(
            status_code=404,
            detail=f"node does not exist: {body.address}",
        )

    storage = session.new_storage()

    try:
        if body.line is None:
            rewind_to_node(target_node, storage)
        else:
            rewind_to_line(target_node, body.line, storage)
    except LensException as e:
        return {"status": "error", "detail": str(e)}

    return {"status": "ok", "address": body.address, "line": body.line}
