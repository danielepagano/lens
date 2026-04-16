from __future__ import annotations

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

router = APIRouter(prefix="/{project_slug}")


class KbItemOut(BaseModel):
    id: str
    tags: list[str]


class KbItemDetailOut(BaseModel):
    id: str
    type: str
    content: str
    tags: list[str]


class KbItemSaveResponse(BaseModel):
    id: str


class KbItemCreateResponse(BaseModel):
    id: str
    content: str


class KbTagResponse(BaseModel):
    id: str
    tags: list[str]
    invalid_dot_tags: list[str] | None = None


class KbCopyResponse(BaseModel):
    source_id: str
    target_id: str


class KbRenameResponse(BaseModel):
    old_id: str
    new_id: str


class KbTemplateResponse(BaseModel):
    type: str
    content: str | None


class KbTemplateSetResponse(BaseModel):
    type: str


class KbWithTagLayerOut(BaseModel):
    parent: str
    children: list[str]


class KbWithTagResponse(BaseModel):
    ids: list[str]
    layers: list[KbWithTagLayerOut] | None = None
    objects: dict[str, KbItemDetailOut] | None = None
    id_to_tags: dict[str, list[str]] | None = None


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
) -> list[KbItemOut]:
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
        ids = kb.list_ids(type_filter=type, include_templates=True)
    return [KbItemOut(id=id_, tags=kb.get_tags(id_)) for id_ in ids]


@router.get("/kb/item/{id:path}")
def kb_get_item(
    id: str,
    session: ProjectSession = Depends(get_session),
) -> KbItemDetailOut:
    try:
        parse_id(id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    kb = session.kb
    objs = kb.get_objects([id])
    obj = objs.get(id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"KB item not found: {id}")
    return KbItemDetailOut(id=obj.id, type=obj.type, content=obj.text, tags=obj.tags)


class KbSaveRequest(BaseModel):
    content: str


@router.put("/kb/item/{id:path}")
def kb_save_item(
    id: str,
    body: KbSaveRequest,
    session: ProjectSession = Depends(get_session),
) -> KbItemSaveResponse:
    try:
        parse_id(id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage = session.new_storage(owner=None)
    kb = KnowledgeStore.for_project(session.project_root, storage=storage)
    kb.store_object(id, body.content)
    return KbItemSaveResponse(id=id)


class KbCreateRequest(BaseModel):
    id: str
    content: str | None = None
    use_template: bool = False


@router.post("/kb/items")
def kb_create_item(
    body: KbCreateRequest,
    session: ProjectSession = Depends(get_session),
) -> KbItemCreateResponse:
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
    return KbItemCreateResponse(id=body.id, content=content)


@router.delete("/kb/item/{id:path}")
def kb_delete_item(
    id: str,
    session: ProjectSession = Depends(get_session),
) -> KbItemSaveResponse:
    try:
        parse_id(id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        kb_delete(id, store=session.kb)
        return KbItemSaveResponse(id=id)
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class KbCopyRequest(BaseModel):
    source_id: str
    target_id: str


@router.post("/kb/copy")
def kb_copy_item(
    body: KbCopyRequest,
    session: ProjectSession = Depends(get_session),
) -> KbCopyResponse:
    try:
        kb_copy(body.source_id, body.target_id, store=session.kb)
        return KbCopyResponse(source_id=body.source_id, target_id=body.target_id)
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class KbRenameRequest(BaseModel):
    old_id: str
    new_id: str


@router.post("/kb/rename")
def kb_rename_item(
    body: KbRenameRequest,
    session: ProjectSession = Depends(get_session),
) -> KbRenameResponse:
    try:
        kb_rename(body.old_id, body.new_id, store=session.kb)
        return KbRenameResponse(old_id=body.old_id, new_id=body.new_id)
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class KbTagRequest(BaseModel):
    add: list[str] = []
    remove: list[str] = []


@router.patch("/kb/item/{id:path}/tags")
def kb_tag_item(
    id: str,
    body: KbTagRequest,
    session: ProjectSession = Depends(get_session),
) -> KbTagResponse:
    try:
        parse_id(id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        current_tags, invalid_tags = kb_tag(
            id, body.add, body.remove, store=session.kb
        )
        return KbTagResponse(id=id, tags=current_tags, invalid_dot_tags=invalid_tags or None)
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class KbTemplateRequest(BaseModel):
    content: str


@router.get("/kb/template/{type}")
def kb_get_template(
    type: str,
    session: ProjectSession = Depends(get_session),
) -> KbTemplateResponse:
    content = kb_template(type, None, store=session.kb)
    return KbTemplateResponse(type=type, content=content)


@router.put("/kb/template/{type}")
def kb_set_template(
    type: str,
    body: KbTemplateRequest,
    session: ProjectSession = Depends(get_session),
) -> KbTemplateSetResponse:
    kb_template(type, body.content, store=session.kb)
    return KbTemplateSetResponse(type=type)


class KbWithTagRequest(BaseModel):
    tags: list[str]
    expand: bool = False
    recurse: int | None = None
    same_type_only: bool = False
    type_filter: str | None = None


@router.post("/kb/with-tag")
def kb_with_tag_query(
    body: KbWithTagRequest,
    session: ProjectSession = Depends(get_session),
) -> KbWithTagResponse:
    try:
        result = kb_with_tag(
            body.tags,
            expand=body.expand,
            recurse=body.recurse,
            same_type_only=body.same_type_only,
            type_filter=body.type_filter,
            store=session.kb,
        )
        layers_out = None
        if result.layers is not None:
            layers_out = [
                KbWithTagLayerOut(parent=parent, children=children)
                for parent, children in result.layers
            ]
        objects_out = None
        if result.objects is not None:
            objects_out = {
                obj_id: KbItemDetailOut(id=obj.id, type=obj.type, content=obj.text, tags=obj.tags)
                for obj_id, obj in result.objects.items()
            }
        return KbWithTagResponse(
            ids=result.ids,
            layers=layers_out,
            objects=objects_out,
            id_to_tags=result.id_to_tags,
        )
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
