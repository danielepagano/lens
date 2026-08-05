from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from lens.core.address import NarrativeAddress
from lens.core.commands.pin import (
    modality_config_set,
    modality_config_unset,
    param_set_value,
    param_unset,
    pin_add,
    pin_block,
    pin_remove,
    pin_unblock,
    var_set,
    var_unset,
    var_value_to_parts,
)
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

PinKind = Literal["kb", "var", "param", "modality"]


class PinRequest(BaseModel):
    kind: PinKind = "kb"
    node: str | None = None
    operation: str | None = None
    ids: list[str] | None = None
    key: str | None = None
    value: Any | None = None
    scope: str | None = None
    modality_id: str | None = None

    @model_validator(mode="after")
    def _validate_pin_shape(self) -> PinRequest:
        k = self.kind
        op = self.operation
        if k == "kb":
            if op not in ("add", "remove", "block", "unblock"):
                raise ValueError("kb pin requires operation add, remove, block, or unblock")
            if not self.ids:
                raise ValueError("kb pin requires non-empty ids")
        elif k == "var":
            if op not in ("set", "unset"):
                raise ValueError("var pin requires operation set or unset")
            if not (self.key and self.key.strip()):
                raise ValueError("var pin requires key")
            if op == "set" and self.value is None:
                raise ValueError("var set requires value")
        elif k == "param":
            if op not in ("set", "unset"):
                raise ValueError("param pin requires operation set or unset")
            if not (self.scope and self.scope.strip()):
                raise ValueError("param pin requires scope (global or operator slug)")
            if not (self.key and self.key.strip()):
                raise ValueError("param pin requires key")
            if op == "set" and self.value is None:
                raise ValueError("param set requires value")
        else:
            assert k == "modality"
            if op not in ("set", "unset"):
                raise ValueError("modality pin requires operation set or unset")
            if not (self.modality_id and self.modality_id.strip()):
                raise ValueError("modality pin requires modality_id")
            if not (self.key and self.key.strip()):
                raise ValueError("modality pin requires key")
            if op == "set" and self.value is None:
                raise ValueError("modality set requires value")
        return self


@router.post("/narrative/pin")
def narrative_pin(
    project_slug: str,
    body: PinRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    node_addr = body.node or "/@cursor"
    try:
        if body.kind == "kb":
            assert body.operation is not None and body.ids is not None
            fn = {
                "add": pin_add,
                "remove": pin_remove,
                "block": pin_block,
                "unblock": pin_unblock,
            }[body.operation]
            count, target_path = fn(session, None, node_addr, body.ids, None)
            return {"status": "ok", "count": count, "target": target_path}
        if body.kind == "var":
            assert body.operation is not None and body.key is not None
            if body.operation == "set":
                count, target_path = var_set(
                    session, body.key, var_value_to_parts(body.value), node_addr, None
                )
            else:
                count, target_path = var_unset(session, body.key, node_addr, None)
            return {"status": "ok", "count": count, "target": target_path}
        if body.kind == "param":
            assert body.operation is not None and body.key is not None and body.scope is not None
            if body.operation == "set":
                count, target_path = param_set_value(
                    session, body.scope, body.key, body.value, node_addr, None
                )
            else:
                count, target_path = param_unset(
                    session, body.scope, body.key, node_addr, None
                )
            return {"status": "ok", "count": count, "target": target_path}
        assert body.kind == "modality"
        assert (
            body.operation is not None
            and body.key is not None
            and body.modality_id is not None
        )
        if body.operation == "set":
            count, target_path = modality_config_set(
                session, body.modality_id, body.key, body.value, node_addr, None
            )
        else:
            count, target_path = modality_config_unset(
                session, body.modality_id, body.key, node_addr, None
            )
        return {"status": "ok", "count": count, "target": target_path}
    except LensException as e:
        return {"status": "error", "detail": str(e)}


class UseNarrativeRequest(BaseModel):
    narrative: str
    narrative_kind: Literal["default", "companion_chat"] = "default"
    companion_as_kb_id: str | None = None
    companion_with_kb_id: str | None = None

    @model_validator(mode="after")
    def _companion_pair(self) -> UseNarrativeRequest:
        if self.narrative_kind == "companion_chat":
            ca = (self.companion_as_kb_id or "").strip()
            cw = (self.companion_with_kb_id or "").strip()
            if not ca or not cw:
                raise ValueError(
                    "companion_chat requires companion_as_kb_id (companion.*) "
                    "and companion_with_kb_id (human.*)"
                )
        elif (self.companion_as_kb_id or "").strip() or (
            self.companion_with_kb_id or ""
        ).strip():
            raise ValueError(
                "companion KB ids are only allowed when narrative_kind is companion_chat"
            )
        return self


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
    ca = body.companion_as_kb_id.strip() if body.companion_as_kb_id else None
    cw = body.companion_with_kb_id.strip() if body.companion_with_kb_id else None
    try:
        hint = use_narrative_for_project(
            slug,
            session.project_root,
            session.git_root,
            narrative_kind=body.narrative_kind,
            companion_as_kb_id=ca,
            companion_with_kb_id=cw,
        )
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    session.active_narrative = get_active_narrative(session.project_root)
    out: dict[str, Any] = {"active": slug}
    if hint:
        out["companion_bootstrap"] = hint
    return out


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
    line = body.line if body.line is not None else addr.line

    try:
        resolved = resolve_address(addr.node_only(), session.project_root)
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
        rewind(target_node, line, storage)
    except LensException as e:
        return {"status": "error", "detail": str(e)}

    return {"status": "ok", "address": body.address, "line": line}


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
