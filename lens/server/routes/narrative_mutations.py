from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lens.core.address import NarrativeAddress
from lens.core.commands.pin import pin_add, pin_remove, pin_block, pin_unblock
from lens.core.commands.rename_node import rename_node
from lens.core.commands.rewind import rewind
from lens.core.commands.use import use_narrative_for_project
from lens.core.exceptions import LensException
from lens.core.project import (
    ProjectSession,
    get_active_narrative,
    resolve_address,
    validate_slug,
)
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")

PinOperation = Literal["add", "remove", "block", "unblock"]


class PinRequest(BaseModel):
    operation: PinOperation = "add"
    ids: list[str]
    node: str | None = None


@router.post("/narrative/pin")
def narrative_pin(
    project_slug: str,
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


class UseNarrativeRequest(BaseModel):
    narrative: str


@router.post("/narrative/narratives/active")
def set_active_narrative(
    project_slug: str,
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


class RewindRequest(BaseModel):
    address: str
    line: int | None = None


@router.post("/narrative/rewind")
def narrative_rewind(
    project_slug: str,
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
        rewind(target_node, body.line, storage)
    except LensException as e:
        return {"status": "error", "detail": str(e)}

    return {"status": "ok", "address": body.address, "line": body.line}


class RenameNodeRequest(BaseModel):
    address: str
    new_slug: str


@router.post("/narrative/rename")
def narrative_rename(
    project_slug: str,
    body: RenameNodeRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    narrative = session.active_narrative
    if narrative is None:
        raise HTTPException(
            status_code=400,
            detail="no active narrative (run 'lens use <slug>' first)",
        )

    new_slug = body.new_slug.strip()
    if not new_slug:
        raise HTTPException(status_code=422, detail="new_slug cannot be empty")
    if not validate_slug(new_slug):
        raise HTTPException(
            status_code=422,
            detail=f"invalid slug '{new_slug}' (alphanumeric, underscores, hyphens only)",
        )

    try:
        addr = NarrativeAddress.parse(body.address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid address: {e}") from e

    try:
        resolved = resolve_address(addr, session.project_root)
        target_node = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not target_node.exists():
        raise HTTPException(
            status_code=404,
            detail=f"node does not exist: {body.address}",
        )

    storage = session.new_storage()
    try:
        effective_slug = rename_node(target_node, new_slug, storage)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"status": "ok", "address": body.address, "new_slug": effective_slug}
