"""Helpers for visual-novel playback routes (registered from narrative.py for path ordering)."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException

from lens.core.annotations import parse_annotations
from lens.core.address import NarrativeAddress
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.pinning import set_tts_cached_rev
from lens.core.project import ProjectSession, has_mount_config
from lens.core.speech import registry as speech_registry
from lens.core.speech.chunks import TTS_CHUNK_REVISION
from lens.core.speech.playback_sequence import (
    PlaybackImageItem,
    PlaybackTextItem,
    PlaybackVideoItem,
    playback_items_for_node,
)
from lens.core.speech.tts_cache_sync import node_uses_tts_cache
from lens.server.streaming import StreamLock, sse_message

_AUDIO_SSE_CHUNK = 48_000


def resolve_narrative_node_or_404(
    session: ProjectSession, address: str
) -> tuple[NarrativeAddress, NarrativeNode]:
    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if addr.narrative is None:
        if session.active_narrative is None:
            raise HTTPException(status_code=400, detail="no active narrative")
        addr = addr.with_narrative(session.active_narrative.narrative_root.name)

    try:
        node_obj = addr.to_node(session.project_root)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"node not found: {address}") from None
    return addr, node_obj


def playback_item_to_json(item: PlaybackTextItem | PlaybackImageItem | PlaybackVideoItem) -> dict[str, Any]:
    if isinstance(item, PlaybackTextItem):
        row: dict[str, Any] = {
            "type": "text",
            "id": item.id,
            "line": item.line,
            "text": item.text,
            "ai_gen": item.ai_gen,
        }
        if item.tts_cached is not None:
            row["tts_cached"] = item.tts_cached
        return row
    if isinstance(item, PlaybackVideoItem):
        return {
            "type": "video",
            "line": item.line,
            "alt": item.alt,
            "url": item.url,
        }
    return {
        "type": "image",
        "line": item.line,
        "alt": item.alt,
        "url": item.url,
    }


def ensure_tts_front_matter_for_playback(session: ProjectSession, node: NarrativeNode) -> None:
    """If the project can use TTS but the node has no ``tts_cached`` block yet, add it before chunking.

    Otherwise the first TTS request would insert front matter and invalidate every ``line`` the client
    already received from :func:`playback_items_for_node`.
    """
    root = session.project_root
    if not has_mount_config(root) or not speech_registry.is_speech_backend_ready(root):
        return
    if node_uses_tts_cache(node):
        return
    storage = session.new_storage(owner=None)
    set_tts_cached_rev(node, TTS_CHUNK_REVISION, storage)


def titlecase_kb_key(kb_id: str) -> str:
    key = kb_id.split(".", 1)[-1] if "." in kb_id else kb_id
    segments = key.replace("_", "-").split("-")
    return " ".join(segment.capitalize() for segment in segments if segment)


def playback_chat_session_params(node: NarrativeNode) -> dict[str, str]:
    if not node.key_path:
        return {}

    session_id = node.key_path[-1]
    parent = NarrativeNode(
        narrative_root=node.narrative_root,
        key_path=node.key_path[:-1],
    )
    try:
        text = parent.md_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    for ann in reversed(parse_annotations(text)):
        if (
            ann.operator == "chat"
            and ann.id == session_id
            and not ann.closing
            and not ann.self_closing
        ):
            result: dict[str, str] = {}
            if "as_kb_id" in ann.params:
                result["as_kb_id"] = str(ann.params["as_kb_id"])
            if "with_kb_id" in ann.params:
                result["with_kb_id"] = str(ann.params["with_kb_id"])
            return result
    return {}


def playback_chat_session_to_json(node: NarrativeNode) -> dict[str, str] | None:
    params = playback_chat_session_params(node)
    if not params:
        return None

    row: dict[str, str] = {}
    as_kb_id = params.get("as_kb_id")
    if isinstance(as_kb_id, str) and as_kb_id.strip():
        row["ai_label"] = titlecase_kb_key(as_kb_id)

    with_kb_id = params.get("with_kb_id")
    if isinstance(with_kb_id, str) and with_kb_id.strip():
        row["human_label"] = titlecase_kb_key(with_kb_id)

    return row


def narrative_playback_payload(session: ProjectSession, node: NarrativeNode, addr: NarrativeAddress) -> dict[str, Any]:
    ensure_tts_front_matter_for_playback(session, node)
    items = playback_items_for_node(node, session.project_root)
    payload: dict[str, Any] = {
        "address": str(addr.node_only()),
        "tts_enabled": node_uses_tts_cache(node),
        "items": [playback_item_to_json(x) for x in items],
    }
    chat_session = playback_chat_session_to_json(node)
    if chat_session is not None:
        payload["chat_session"] = chat_session
    return payload


def lens_tts_http_exception(exc: LensException) -> HTTPException:
    msg = str(exc)
    if "no TTS chunk" in msg:
        return HTTPException(status_code=404, detail=msg)
    return HTTPException(status_code=400, detail=msg)


async def tts_chunk_sse_from_bytes(
    data: bytes,
    content_type: str,
    from_cache: bool,
    lock: StreamLock,
) -> AsyncIterator[str]:
    try:
        yield sse_message(
            {
                "type": "start",
                "content_type": content_type,
                "from_cache": from_cache,
            }
        )
        for i in range(0, len(data), _AUDIO_SSE_CHUNK):
            piece = data[i : i + _AUDIO_SSE_CHUNK]
            yield sse_message(
                {
                    "type": "audio",
                    "b64": base64.b64encode(piece).decode("ascii"),
                }
            )
        yield sse_message({"type": "done"})
    except Exception as e:
        yield sse_message({"type": "error", "message": str(e)})
    finally:
        lock.release()
