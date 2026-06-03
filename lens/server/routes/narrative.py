from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, is_dataset_root
from lens.server.dependencies import get_session, get_stream_lock, get_tts_coordinator
from lens.server.routes.narrative_playback import (
    lens_tts_http_exception,
    narrative_playback_payload,
    resolve_narrative_node_or_404,
    tts_chunk_sse_from_bytes,
)
from lens.server.streaming import StreamLock
from lens.server.tts_chunk_coordinator import TtsChunkCoordinator

router = APIRouter(prefix="/{project_slug}")

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _node_to_dict(node: NarrativeNode) -> dict[str, Any]:
    children = [_node_to_dict(node.child_node(key)) for key in node.child_keys()]
    return {
        "address": str(node.to_address()),
        "key": node.key_path[-1] if node.key_path else node.narrative_root.name,
        "children": children,
    }


@router.get("/narrative/tree")
def tree(project_slug: str, session: ProjectSession = Depends(get_session)) -> list[dict[str, Any]]:
    if is_dataset_root(session.project_root):
        return []
    if session.active_narrative is None:
        return []
    root = session.active_narrative
    return [_node_to_dict(root)]


@router.get("/narrative/node/{address:path}/playback")
def narrative_node_playback(
    project_slug: str,
    address: str,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    _ = project_slug
    if is_dataset_root(session.project_root):
        raise HTTPException(status_code=404, detail="no narrative nodes in dataset mode")
    addr, node_obj = resolve_narrative_node_or_404(session, address)
    return narrative_playback_payload(session, node_obj, addr)


@router.post("/narrative/node/{address:path}/tts/render")
async def narrative_node_tts_render(
    project_slug: str,
    address: str,
    line: int,
    chunk_id: str,
    voice_id: str | None = None,
    model_id: str | None = None,
    session: ProjectSession = Depends(get_session),
    coordinator: TtsChunkCoordinator = Depends(get_tts_coordinator),
) -> JSONResponse:
    _ = project_slug
    if is_dataset_root(session.project_root):
        raise HTTPException(status_code=404, detail="no narrative nodes in dataset mode")
    _addr, node_obj = resolve_narrative_node_or_404(session, address)
    try:
        status = await coordinator.start_render_if_needed(
            session,
            node_obj,
            line=line,
            chunk_id=chunk_id,
            voice_id=voice_id,
            model_id=model_id,
        )
    except LensException as e:
        raise lens_tts_http_exception(e) from e
    code = 200 if status == "ready" else 202
    return JSONResponse({"status": status}, status_code=code)


@router.get("/narrative/node/{address:path}/tts")
async def narrative_node_tts(
    project_slug: str,
    address: str,
    line: int,
    chunk_id: str,
    voice_id: str | None = None,
    model_id: str | None = None,
    session: ProjectSession = Depends(get_session),
    coordinator: TtsChunkCoordinator = Depends(get_tts_coordinator),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    _ = project_slug
    if is_dataset_root(session.project_root):
        raise HTTPException(status_code=404, detail="no narrative nodes in dataset mode")
    _addr, node_obj = resolve_narrative_node_or_404(session, address)
    try:
        data, ctype, from_cache = await coordinator.get_chunk_audio(
            session,
            node_obj,
            line=line,
            chunk_id=chunk_id,
            voice_id=voice_id,
            model_id=model_id,
        )
    except LensException as e:
        raise lens_tts_http_exception(e) from e

    lock.acquire("tts-chunk")
    return StreamingResponse(
        tts_chunk_sse_from_bytes(data, ctype, from_cache, lock),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/narrative/node/{address:path}")
def node(
    project_slug: str, address: str, session: ProjectSession = Depends(get_session)
) -> dict[str, Any]:
    _ = project_slug
    if is_dataset_root(session.project_root):
        raise HTTPException(status_code=404, detail="no narrative nodes in dataset mode")

    addr, node_obj = resolve_narrative_node_or_404(session, address)
    try:
        content = node_obj.md_path().read_text()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"node not found: {address}")

    return {
        "address": str(addr.node_only()),
        "content": content,
        "children": node_obj.child_keys(),
    }
