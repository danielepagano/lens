"""Image generation over HTTP: SSE stream + incremental save."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, model_validator

from lens.core.commands.generate import plan_from_persisted_params, prepare_batch, save_generated_item
from lens.core.exceptions import LensException
from lens.core.image.backend import ImageError
from lens.core.image.spec import Done, Error, ItemReady, Progress
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session, get_stream_lock
from lens.server.streaming import StreamLock, sse_message, watch_client_disconnect

router = APIRouter(prefix="/{project_slug}")


class GenerateStreamBody(BaseModel):
    prompt: str | None = None
    model: str | None = None
    aspect: str | None = None
    size: str | None = None
    batch: int | None = None
    slug: str | None = None
    negative: str | None = None
    from_: str | None = None
    refs: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_from_key(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = cast(dict[str, Any], value.copy())
            if "from" in data and "from_" not in data:
                data["from_"] = data["from"]
            return data
        return value

    @model_validator(mode="after")
    def at_least_prompt_or_from(self) -> "GenerateStreamBody":
        p = (self.prompt or "").strip()
        f = (self.from_ or "").strip()
        if not p and not f:
            raise ValueError("prompt is required, or use 'from' with a batch sidecar")
        return self


class BatchParamsBody(BaseModel):
    prompt_raw: str
    prompt_resolved: str
    model_id: str
    aspect_ratio: str
    size: str
    batch_size: int
    negative: str | None = None
    refs: list[str] | None = None


class ItemBody(BaseModel):
    index: int
    ext: str
    b64: str


class SaveBody(BaseModel):
    slug: str
    batch_seq: int | None = None
    batch_params: BatchParamsBody
    item: ItemBody


async def _stream_generate_events(
    plan: Any,
    image_backend: Any,
    lock: StreamLock,
    request: Request,
    session: ProjectSession,
) -> AsyncIterator[str]:
    watcher = asyncio.create_task(watch_client_disconnect(request, lock, session))
    try:
        if lock.cancel_event.is_set():
            yield sse_message({"type": "error", "message": "cancelled before start"})
            return
        start_payload = {
            "type": "start",
            "slug": plan.slug,
            "model_id": plan.descriptor.id,
            "api": plan.descriptor.api,
            "model": plan.descriptor.model,
            "aspect": plan.spec.aspect_ratio,
            "size": plan.spec.size,
            "batch_size": plan.spec.batch,
            "prompt_raw": plan.prompt_raw,
            "prompt_resolved": plan.prompt_resolved,
            "negative": plan.spec.negative_prompt,
        }
        if plan.reference_paths:
            start_payload["refs"] = list(plan.reference_paths)
        yield sse_message(start_payload)
        async for event in image_backend.generate(plan.spec):
            if lock.cancel_event.is_set():
                yield sse_message({"type": "error", "message": "cancelled"})
                return
            if isinstance(event, Progress):
                yield sse_message(
                    {
                        "type": "progress",
                        "phase": event.phase,
                        "pct": event.pct,
                        "message": event.message,
                    }
                )
            elif isinstance(event, ItemReady):
                b64 = base64.b64encode(event.data).decode("ascii")
                yield sse_message(
                    {
                        "type": "item",
                        "index": event.index,
                        "ext": event.ext,
                        "b64": b64,
                        "metadata": event.metadata,
                    }
                )
            elif isinstance(event, Error):
                yield sse_message({"type": "error", "message": event.message})
                return
            elif isinstance(event, Done):
                break
        yield sse_message({"type": "done"})
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        lock.release()


@router.post("/generate")
async def generate_stream(
    project_slug: str,
    body: GenerateStreamBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    _ = project_slug
    raw_from = (body.from_ or "").strip()
    from_path: Path | str | None = Path(raw_from) if raw_from else None
    ref_paths = [x.strip() for x in (body.refs or []) if x.strip()]
    try:
        plan, image_backend = prepare_batch(
            session,
            (body.prompt or "").strip() or None,
            aspect=body.aspect,
            size=body.size,
            batch=body.batch,
            slug=body.slug,
            negative_prompt=body.negative,
            model_id=body.model,
            from_sidecar=from_path,
            ref_paths=ref_paths or None,
        )
    except (LensException, ImageError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        lock.acquire("media-generate")
    except HTTPException:
        raise
    return StreamingResponse(
        _stream_generate_events(plan, image_backend, lock, request, session),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/generate/save")
def save_generated(
    project_slug: str,
    body: SaveBody,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    _ = project_slug
    p = body.batch_params
    try:
        data = base64.b64decode(body.item.b64, validate=True)
    except binascii.Error as e:
        raise HTTPException(status_code=400, detail="invalid base64 in item.b64") from e
    try:
        ref_save = [x.strip() for x in (p.refs or []) if x.strip()]
        plan = plan_from_persisted_params(
            session,
            slug=body.slug,
            prompt_raw=p.prompt_raw,
            prompt_resolved=p.prompt_resolved,
            model_id=p.model_id,
            aspect_ratio=p.aspect_ratio,
            size=p.size,
            batch_size=p.batch_size,
            negative_prompt=p.negative,
            reference_paths=ref_save or None,
        )
    except (LensException, ImageError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        out = save_generated_item(
            session,
            plan,
            item_data=data,
            ext=body.item.ext,
            batch_seq=body.batch_seq,
        )
    except (LensException, ImageError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "batch_seq": out.batch_seq,
        "result_seq": out.result_seq,
        "path": out.path,
        "sidecar_path": out.sidecar_path,
        "sidecar_created": out.sidecar_created,
    }
