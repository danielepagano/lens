from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()


@router.get("/health")
def health(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    return {"status": "ok"}

