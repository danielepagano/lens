from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lens.core.commands.pin import pin_add, pin_remove, pin_block, pin_unblock
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()

PinOperation = Literal["add", "remove", "block", "unblock"]


class PinRequest(BaseModel):
    operation: PinOperation = "add"
    ids: list[str]
    node: str | None = None


@router.post("/narrative/pin")
def narrative_pin(
    body: PinRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        fn = {
            "add": pin_add,
            "remove": pin_remove,
            "block": pin_block,
            "unblock": pin_unblock,
        }[body.operation]
        count, target_path = fn(session, None, body.node or "/@cursor", body.ids, None)
        return {"status": "ok", "count": count, "target": target_path}
    except LensException as e:
        return {"status": "error", "detail": str(e)}
