from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from lens.core.commands.kb import (
    kb_copy,
    kb_delete,
    kb_rename,
    kb_tag,
    kb_template,
    kb_with_tag,
)
from lens.core.exceptions import LensException
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


@router.delete("/kb/item/{id:path}")
def kb_delete_item(
    id: str,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        kb_delete(id)
        return {"status": "ok", "id": id}
    except LensException as e:
        return {"status": "error", "detail": str(e)}


class KbCopyRequest(BaseModel):
    source_id: str
    target_id: str


@router.post("/kb/copy")
def kb_copy_item(
    body: KbCopyRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        kb_copy(body.source_id, body.target_id)
        return {"status": "ok", "source_id": body.source_id, "target_id": body.target_id}
    except LensException as e:
        return {"status": "error", "detail": str(e)}


class KbRenameRequest(BaseModel):
    old_id: str
    new_id: str


@router.post("/kb/rename")
def kb_rename_item(
    body: KbRenameRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        kb_rename(body.old_id, body.new_id)
        return {"status": "ok", "old_id": body.old_id, "new_id": body.new_id}
    except LensException as e:
        return {"status": "error", "detail": str(e)}


class KbTagRequest(BaseModel):
    add: list[str] = []
    remove: list[str] = []


@router.patch("/kb/item/{id:path}/tags")
def kb_tag_item(
    id: str,
    body: KbTagRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        current_tags, invalid_tags = kb_tag(id, body.add, body.remove)
        result: dict[str, Any] = {"status": "ok", "id": id, "tags": current_tags}
        if invalid_tags:
            result["invalid_dot_tags"] = invalid_tags
        return result
    except LensException as e:
        return {"status": "error", "detail": str(e)}


class KbTemplateRequest(BaseModel):
    content: str


@router.get("/kb/template/{type}")
def kb_get_template(
    type: str,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    content = kb_template(type, None)
    if content is None:
        return {"type": type, "content": None}
    return {"type": type, "content": content}


@router.put("/kb/template/{type}")
def kb_set_template(
    type: str,
    body: KbTemplateRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    kb_template(type, body.content)
    return {"status": "ok", "type": type}


class KbWithTagRequest(BaseModel):
    tags: list[str]
    expand: bool = False
    recurse: int | None = None
    same_type_only: bool = False


@router.post("/kb/with-tag")
def kb_with_tag_query(
    body: KbWithTagRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = kb_with_tag(
            body.tags,
            expand=body.expand,
            recurse=body.recurse,
            same_type_only=body.same_type_only,
        )
        response: dict[str, Any] = {"ids": result.ids}
        if result.layers is not None:
            response["layers"] = [
                {"parent": parent, "children": children}
                for parent, children in result.layers
            ]
        if result.objects is not None:
            response["objects"] = {
                obj_id: {"id": obj.id, "type": obj.type, "content": obj.text, "tags": obj.tags}
                for obj_id, obj in result.objects.items()
            }
        if result.id_to_tags is not None:
            response["id_to_tags"] = result.id_to_tags
        return response
    except LensException as e:
        return {"status": "error", "detail": str(e)}
