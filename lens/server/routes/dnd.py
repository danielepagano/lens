from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lens.core.project import ProjectSession, get_selected_datasets
from lens.dnd.commands.balance_encounter import compute_encounters
from lens.server.dependencies import get_session

router = APIRouter()


class RequiredEntry(BaseModel):
    id: str
    count: int


class BalanceRequest(BaseModel):
    required: list[RequiredEntry] = []
    optional: list[str] = []
    difficulty: str = "moderate"
    pcs: list[int] = []
    allies: list[str] = []


@router.post("/dnd/balance")
def dnd_balance(
    body: BalanceRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    datasets = get_selected_datasets(session.project_root)
    if "dnd" not in datasets:
        raise HTTPException(
            status_code=404,
            detail="dnd dataset is not active in this project",
        )

    required_raw = [{"id": r.id, "count": r.count} for r in body.required]
    result = compute_encounters(
        required_raw,
        body.optional,
        body.difficulty,
        body.pcs,
        body.allies,
        session.kb,
    )

    return {"status": "ok", "result": result}
