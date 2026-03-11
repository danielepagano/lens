from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from lens.core.knowledge import KnowledgeStore, parse_id
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session

router = APIRouter()


@router.get("/kb/types")
def kb_types(session: ProjectSession = Depends(get_session)) -> list[str]:
    return session.kb.list_types()


@router.get("/kb/tags")
def kb_tags(
    type: str | None = Query(None),
    prefix: str | None = Query(None),
    session: ProjectSession = Depends(get_session),
) -> list[str]:
    return session.kb.list_unique_tags(type_filter=type, prefix_filter=prefix)


@router.get("/kb/items")
def kb_items(
    type: str | None = Query(None),
    tags: str | None = Query(None),
    session: ProjectSession = Depends(get_session),
) -> list[dict[str, Any]]:
    kb = session.kb
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    if tag_list:
        from lens.core.commands.kb import parse_tag_groups

        groups = parse_tag_groups(tag_list)
        ids = kb.get_ids_with_tag_groups(groups)
        if type:
            type_prefix = type.lower() + "."
            ids = [i for i in ids if i.startswith(type_prefix)]
    else:
        ids = kb.list_ids(type_filter=type)
    return [{"id": id_, "tags": kb.get_tags(id_)} for id_ in ids]


@router.get("/kb/item/{id:path}")
def kb_get_item(
    id: str,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        parse_id(id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    kb = session.kb
    objs = kb.get_objects([id])
    obj = objs.get(id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"KB item not found: {id}")
    return {"id": obj.id, "type": obj.type, "content": obj.text, "tags": obj.tags}


class KbSaveRequest(BaseModel):
    content: str


@router.put("/kb/item/{id:path}")
def kb_save_item(
    id: str,
    body: KbSaveRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        parse_id(id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage = session.new_storage(owner=None)
    kb = KnowledgeStore.for_project(session.project_root, storage=storage)
    kb.store_object(id, body.content)
    return {"id": id}


class KbCreateRequest(BaseModel):
    id: str
    content: str | None = None
    use_template: bool = False


@router.post("/kb/items")
def kb_create_item(
    body: KbCreateRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        parse_id(body.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage = session.new_storage(owner=None)
    kb = KnowledgeStore.for_project(session.project_root, storage=storage)
    kb.store_object(body.id, body.content, use_template=body.use_template)
    objs = kb.get_objects([body.id])
    obj = objs.get(body.id)
    content = obj.text if obj else (body.content or "")
    return {"id": body.id, "content": content}
