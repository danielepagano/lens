from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from lens.core.commands.check import run_project_check
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()

@router.get("/health")
def health(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    result = run_project_check(session.project_root)
    errors = [line for line in result.lines if line.severity == "error"]
    if errors:
        detail = "; ".join(f"{line.topic}: {line.detail}" for line in errors)
        raise HTTPException(status_code=503, detail=f"health check failed: {detail}")
    return {"status": "ok"}
