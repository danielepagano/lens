from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lens.core.commands.use import use_narrative_for_project
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, get_active_narrative, validate_slug
from lens.server.dependencies import get_session

router = APIRouter()


@router.get("/narratives")
def list_narratives(session: ProjectSession = Depends(get_session)) -> dict[str, Any]:
    narrative_dir = session.project_root / "narrative"
    narratives: list[str] = []
    if narrative_dir.exists():
        for d in sorted(narrative_dir.iterdir()):
            if d.is_dir() and NarrativeNode(narrative_root=d, key_path=()).exists():
                narratives.append(d.name)
    active = (
        session.active_narrative.narrative_root.name
        if session.active_narrative is not None
        else None
    )
    return {"narratives": narratives, "active": active}


class UseNarrativeRequest(BaseModel):
    narrative: str


@router.post("/narratives/active")
def set_active_narrative(
    body: UseNarrativeRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    slug = body.narrative.strip()
    if not slug:
        raise HTTPException(status_code=422, detail="narrative slug cannot be empty")
    if not validate_slug(slug):
        raise HTTPException(
            status_code=422,
            detail=f"invalid slug '{slug}' (alphanumeric, underscores, hyphens only)",
        )
    use_narrative_for_project(slug, session.project_root, session.git_root)
    session.active_narrative = get_active_narrative(session.project_root)
    return {"active": slug}
