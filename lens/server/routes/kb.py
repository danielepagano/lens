from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
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
from lens.core.knowledge import KnowledgeStore, parse_id, validate_ids_exist
from lens.core.llm import llm_progress_scope
from lens.core.now import set_request_timezone
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session, get_stream_lock
from lens.server.streaming import StreamLock, operator_stream_response

router = APIRouter(prefix="/{project_slug}")


def _direct_edit_kb(session: ProjectSession) -> KnowledgeStore:
    """KnowledgeStore for a hand edit made by the user in the UI.

    Writes stage themselves and leave any pending operator preview alone (see
    "Direct user edits" in docs/design.md).  The AI-driven ``kb_edit`` route is
    deliberately *not* routed here: generated content stays a reviewable
    transaction.
    """
    return KnowledgeStore.for_project(
        session.project_root, storage=session.new_direct_edit_storage()
    )


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
    _direct_edit_kb(session).store_object(id, body.content)
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
    kb = _direct_edit_kb(session)
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
        kb_delete(id, store=_direct_edit_kb(session))
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        session.kb.evict_tag_cache()
    return KbItemSaveResponse(id=id)


class KbCopyRequest(BaseModel):
    source_id: str
    target_id: str


@router.post("/kb/copy")
def kb_copy_item(
    body: KbCopyRequest,
    session: ProjectSession = Depends(get_session),
) -> KbCopyResponse:
    try:
        kb_copy(body.source_id, body.target_id, store=_direct_edit_kb(session))
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        session.kb.evict_tag_cache()
    return KbCopyResponse(source_id=body.source_id, target_id=body.target_id)


class KbRenameRequest(BaseModel):
    old_id: str
    new_id: str


@router.post("/kb/rename")
def kb_rename_item(
    body: KbRenameRequest,
    session: ProjectSession = Depends(get_session),
) -> KbRenameResponse:
    try:
        kb_rename(body.old_id, body.new_id, store=_direct_edit_kb(session))
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        session.kb.evict_tag_cache()
    return KbRenameResponse(old_id=body.old_id, new_id=body.new_id)


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
            id, body.add, body.remove, store=_direct_edit_kb(session)
        )
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        session.kb.evict_tag_cache()
    return KbTagResponse(id=id, tags=current_tags, invalid_dot_tags=invalid_tags or None)


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
    kb_template(type, body.content, store=_direct_edit_kb(session))
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


class KbEditBody(BaseModel):
    id: str
    instruction: str
    context: str | None = None
    include_template: bool = False
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    reasoning: str | None = None
    retry: bool = False


@router.post("/kb/edit")
async def kb_edit_endpoint(
    body: KbEditBody,
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    try:
        parse_id(body.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    all_ids = list(body.pins) + list(body.unpins)
    if all_ids:
        try:
            validate_ids_exist(session.project_root, all_ids)
        except LensException as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    set_request_timezone(request.headers.get("Time-Zone"))

    from lens.core.commands.kb import kb_edit as _kb_edit

    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def on_token(chunk: str) -> None:
        event_queue.put_nowait({"type": "token", "text": chunk})

    async def on_llm_progress(phase: str, detail: dict[str, Any]) -> None:
        payload: dict[str, Any] = {"type": "progress", "phase": phase}
        for key, val in detail.items():
            if isinstance(val, (str, int, float, bool)) or val is None:
                payload[key] = val
        await event_queue.put(payload)

    lock.acquire("kb-edit")
    event_queue.put_nowait({"type": "target", "node": body.id})
    event_queue.put_nowait({
        "type": "progress",
        "phase": "operator_started",
        "operator": "kb-edit",
        "message": "Starting kb edit…",
    })

    async def _run_kb_edit() -> None:
        try:
            async with llm_progress_scope(on_llm_progress):
                await _kb_edit(
                    id=body.id,
                    instruction=body.instruction,
                    context_address=body.context,
                    project_root=session.project_root,
                    pins=list(body.pins),
                    unpins=list(body.unpins),
                    include_template=body.include_template,
                    llm_id=body.llm_id,
                    reasoning=body.reasoning,
                    retry=body.retry,
                    on_token=on_token,
                    cancel_event=lock.cancel_event,
                )
            await event_queue.put({
                "type": "done",
                "operator": "kb-edit",
                "node": body.id,
                "interrupted": False,
            })
        except LensException as e:
            await event_queue.put({"type": "error", "message": str(e)})
        except asyncio.CancelledError:
            await event_queue.put({
                "type": "done",
                "operator": "kb-edit",
                "node": body.id,
                "interrupted": True,
            })
        except Exception as e:
            await event_queue.put({"type": "error", "message": str(e)})
        finally:
            await event_queue.put(None)
            session.kb.evict_tag_cache()

    task = asyncio.ensure_future(_run_kb_edit())
    lock.task = task

    return operator_stream_response(event_queue, lock, request, session)
