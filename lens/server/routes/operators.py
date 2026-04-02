"""AI operator execution over HTTP with SSE streaming."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lens.core.commands.rollback import execute_rollback
from lens.core.exceptions import LensException
from lens.core.knowledge import validate_ids_exist
from lens.core.operator import OperatorError
from lens.core.llm import llm_progress_scope
from lens.core.project import ProjectSession
from lens.server.dependencies import get_session
from lens.server.streaming import StreamLock, operator_stream_response

router = APIRouter()
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class WriteBody(BaseModel):
    prompt: str | None = None
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    retry: bool = False


class WriteManualBody(BaseModel):
    text: str


class PlayBody(BaseModel):
    prompt: str | None = None
    module_id: str | None = None
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    retry: bool = False
    end: bool = False
    as_pc: str | None = None
    do_pass: bool = False
    slug: str | None = None


class DesignBody(BaseModel):
    prompt: str | None = None
    module_id: str | None = None
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    retry: bool = False
    end: bool = False
    slug: str | None = None


class EditBody(BaseModel):
    address: str
    start_line: int
    end_line: int
    prompt: str | None = None
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    retry: bool = False
    replace: bool = False


class SectionStartBody(BaseModel):
    id: str
    pins: list[str] = []
    unpins: list[str] = []


class SectionEndBody(BaseModel):
    llm_id: str | None = None


class AdvanceBody(BaseModel):
    days: int = 1
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    retry: bool = False
    feedback: str | None = None
    end: bool = False


class CollateBody(BaseModel):
    id: str
    address: str
    start_line: int
    end_line: int
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_narrative(session: ProjectSession) -> Any:
    """Return active narrative or raise 400."""
    narrative = session.active_narrative
    if narrative is None:
        raise HTTPException(
            status_code=400,
            detail="No active narrative (run 'lens use <slug>' first)",
        )
    return narrative


def _validate_pins(session: ProjectSession, pins: list[str], unpins: list[str]) -> None:
    try:
        validate_ids_exist(session.project_root, pins + unpins)
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _play_pins_with_encounter_expand(pins: list[str]) -> list[str]:
    """Ensure ``encounter.*`` pins use one-hop link expansion (``+``) in play."""
    return [p + "+" if p.startswith("encounter.") and not p.endswith("+") else p for p in pins]


def _resolve_node(node_address: str | Callable[[], str]) -> str:
    return node_address() if callable(node_address) else node_address


def _make_on_llm_progress(
    event_queue: asyncio.Queue[dict[str, Any] | None],
) -> Any:
    async def on_llm_progress(phase: str, detail: dict[str, Any]) -> None:
        payload: dict[str, Any] = {"type": "progress", "phase": phase}
        for key, val in detail.items():
            if isinstance(val, (str, int, float, bool)) or val is None:
                payload[key] = val
        await event_queue.put(payload)

    return on_llm_progress


async def _run_operator_task(
    coro_fn: Any,
    event_queue: asyncio.Queue[dict[str, Any] | None],
    operator_name: str,
    node_address: str | Callable[[], str],
    session: ProjectSession,
    *,
    extra_done_fields: dict[str, Any] | None = None,
) -> None:
    """Wrapper that runs an operator coroutine and pushes events to the queue."""
    progress = _make_on_llm_progress(event_queue)
    try:
        async with llm_progress_scope(progress):
            try:
                result = await coro_fn()
                done_payload: dict[str, Any] = {
                    "type": "done",
                    "operator": operator_name,
                    "node": _resolve_node(node_address),
                    "interrupted": False,
                }
                if extra_done_fields:
                    done_payload.update(extra_done_fields)
                if result is not None:
                    # Design returns KbExtractResult
                    if hasattr(result, "inserted"):
                        done_payload["inserted"] = result.inserted
                        done_payload["updated"] = result.updated
                        done_payload["errors"] = result.errors
                    # Section end returns key string
                    elif isinstance(result, str):
                        done_payload["section_key"] = result
                await event_queue.put(done_payload)
            except OperatorError as e:
                execute_rollback(session)
                _log.warning("operator %s failed: %s", operator_name, e)
                await event_queue.put({"type": "error", "message": str(e)})
            except LensException as e:
                execute_rollback(session)
                _log.warning("operator %s lens error: %s", operator_name, e)
                await event_queue.put({"type": "error", "message": str(e)})
            except asyncio.CancelledError:
                _log.info("operator %s task cancelled", operator_name)
                await event_queue.put({
                    "type": "done",
                    "operator": operator_name,
                    "node": _resolve_node(node_address),
                    "interrupted": True,
                })
            except KeyboardInterrupt:
                await event_queue.put({
                    "type": "done",
                    "operator": operator_name,
                    "node": _resolve_node(node_address),
                    "interrupted": True,
                })
            except Exception as e:
                _log.exception("operator %s unexpected error", operator_name)
                await event_queue.put({"type": "error", "message": str(e)})
    finally:
        await event_queue.put(None)  # sentinel
        session.kb.evict_tag_cache()


def _make_on_token(
    event_queue: asyncio.Queue[dict[str, Any] | None],
) -> Any:
    async def on_token(chunk: str) -> None:
        await event_queue.put({"type": "token", "text": chunk})
    return on_token


def _start_operator_stream(
    lock: StreamLock,
    event_queue: asyncio.Queue[dict[str, Any] | None],
    session: ProjectSession,
    operator_name: str,
    node_address: str | Callable[[], str],
    coro_fn: Any,
) -> StreamingResponse:
    """Acquire the stream lock, launch operator task, return SSE response."""
    lock.acquire(operator_name)
    event_queue.put_nowait({"type": "target", "node": _resolve_node(node_address)})
    event_queue.put_nowait({
        "type": "progress",
        "phase": "operator_started",
        "operator": operator_name,
        "message": f"Starting {operator_name}…",
    })

    task = asyncio.ensure_future(
        _run_operator_task(
            coro_fn, event_queue, operator_name, node_address, session,
        )
    )
    lock.task = task

    return operator_stream_response(event_queue, lock)


# ---------------------------------------------------------------------------
# Operator endpoints
# ---------------------------------------------------------------------------

@router.post("/operator/write")
async def operator_write(
    body: WriteBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    from lens.core.operators.write import WriteOperator

    narrative = _require_narrative(session)
    _validate_pins(session, body.pins, body.unpins)
    cursor = narrative.find_cursor()
    node_addr = str(cursor.to_address())

    lock: StreamLock = request.app.state.stream_lock
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    on_token = _make_on_token(event_queue)

    def coro_fn() -> Any:
        return WriteOperator.run_inline(
            session=session,
            narrative=narrative,
            prompt=body.prompt,
            pins=body.pins,
            unpins=body.unpins,
            llm_id=body.llm_id,
            retry=body.retry,
            on_token=on_token,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(lock, event_queue, session, "write", node_addr, coro_fn)


@router.post("/operator/write/manual")
async def operator_write_manual(
    body: WriteManualBody,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    from lens.core.operators.write import WriteOperator

    narrative = _require_narrative(session)
    try:
        node_addr = WriteOperator.run_manual(
            session=session,
            narrative=narrative,
            text=body.text,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "ok", "node": node_addr}


@router.post("/operator/play")
async def operator_play(
    body: PlayBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    from lens.rpg.operators.play import PlayOperator

    narrative = _require_narrative(session)
    pins = list(body.pins)
    unpins = list(body.unpins)
    if body.module_id is not None and body.module_id.strip():
        module_key = body.module_id.strip()
        pins_for_validation = pins + [f"rules.{module_key}"]
        _validate_pins(session, pins_for_validation, unpins)
    else:
        module_key = None
        _validate_pins(session, pins, unpins)
    pins = _play_pins_with_encounter_expand(pins)
    cursor = narrative.find_cursor()
    target_ref: list[str] = [str(cursor.to_address())]

    lock: StreamLock = request.app.state.stream_lock
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_stream_target(addr: str) -> None:
        target_ref[0] = addr
        await event_queue.put({"type": "target", "node": addr})

    on_token = _make_on_token(event_queue)

    extra_params: dict[str, Any] | None = None
    if body.as_pc is not None or body.do_pass:
        extra_params = {}
        if body.as_pc is not None:
            extra_params["as_pc"] = body.as_pc
        if body.do_pass:
            extra_params["pass"] = True

    def coro_fn() -> Any:
        return PlayOperator.run_session(
            session=session,
            narrative=narrative,
            prompt=body.prompt,
            module_id=module_key,
            pins=pins,
            unpins=unpins,
            llm_id=body.llm_id,
            retry=body.retry,
            end=body.end,
            slug=body.slug if not body.end and not body.retry else None,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=lock.cancel_event,
            extra_params=extra_params,
        )

    return _start_operator_stream(
        lock, event_queue, session, "play", lambda: target_ref[0], coro_fn
    )


@router.post("/operator/advance")
async def operator_advance(
    body: AdvanceBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    from lens.rpg.operators.advance import AdvanceOperator

    narrative = _require_narrative(session)
    _validate_pins(session, body.pins, body.unpins)
    cursor = narrative.find_cursor()
    target_ref: list[str] = [str(cursor.to_address())]

    lock: StreamLock = request.app.state.stream_lock
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_stream_target(addr: str) -> None:
        target_ref[0] = addr
        await event_queue.put({"type": "target", "node": addr})

    on_token = _make_on_token(event_queue)

    def coro_fn() -> Any:
        return AdvanceOperator.run_advance(
            session=session,
            narrative=narrative,
            increment=body.days,
            pins=body.pins,
            unpins=body.unpins,
            llm_id=body.llm_id,
            retry=body.retry,
            feedback=body.feedback,
            end=body.end,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(
        lock, event_queue, session, "advance", lambda: target_ref[0], coro_fn
    )


@router.post("/operator/design")
async def operator_design(
    body: DesignBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    from lens.core.operators.design import DesignOperator

    narrative = _require_narrative(session)
    pins = list(body.pins)
    unpins = list(body.unpins)
    if body.module_id is not None and body.module_id.strip():
        module_key = body.module_id.strip()
        pins_for_validation = pins + [f"design.{module_key}"]
        _validate_pins(session, pins_for_validation, unpins)
    else:
        module_key = None
        _validate_pins(session, pins, unpins)
    cursor = narrative.find_cursor()
    target_ref: list[str] = [str(cursor.to_address())]

    lock: StreamLock = request.app.state.stream_lock
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_stream_target(addr: str) -> None:
        target_ref[0] = addr
        await event_queue.put({"type": "target", "node": addr})

    on_token = _make_on_token(event_queue)

    def coro_fn() -> Any:
        return DesignOperator.run_design(
            session=session,
            narrative=narrative,
            prompt=body.prompt,
            module_id=module_key,
            pins=pins,
            unpins=unpins,
            llm_id=body.llm_id,
            retry=body.retry,
            end=body.end,
            slug=body.slug if not body.end and not body.retry else None,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(
        lock, event_queue, session, "design", lambda: target_ref[0], coro_fn
    )



@router.post("/operator/edit")
async def operator_edit(
    body: EditBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    from lens.core.address import NarrativeAddress
    from lens.core.operators.edit import EditOperator
    from lens.core.project import resolve_address

    _require_narrative(session)
    _validate_pins(session, body.pins, body.unpins)

    try:
        addr = NarrativeAddress.parse(body.address)
        resolved = resolve_address(addr, session.project_root)
        target_node = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not target_node.exists():
        raise HTTPException(status_code=400, detail=f"Node does not exist: {body.address}")

    node_addr = str(resolved)
    rel_path = str(target_node.md_path().relative_to(session.git_root))
    ann_id = EditOperator.ann_id(body.start_line, body.end_line)

    lock: StreamLock = request.app.state.stream_lock
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    on_token = _make_on_token(event_queue)

    def coro_fn() -> Any:
        return EditOperator.run_mutation(
            session=session,
            node=target_node,
            rel_path=rel_path,
            ann_id=ann_id,
            start_line=body.start_line,
            end_line=body.end_line,
            prompt=body.prompt,
            manual=body.replace,
            pins=body.pins,
            unpins=body.unpins,
            llm_id=body.llm_id,
            retry=body.retry,
            on_token=on_token,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(lock, event_queue, session, "edit", node_addr, coro_fn)


@router.post("/operator/section/start")
async def operator_section_start(
    body: SectionStartBody,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    from lens.core.operators.section import SectionOperator

    narrative = _require_narrative(session)
    _validate_pins(session, body.pins, body.unpins)
    try:
        child = await SectionOperator.run_start(
            session=session,
            narrative=narrative,
            id=body.id,
            pins=body.pins,
            unpins=body.unpins,
        )
        return {"status": "ok", "node": str(child.to_address())}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/operator/section/end")
async def operator_section_end(
    body: SectionEndBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    from lens.core.operators.section import SectionOperator

    narrative = _require_narrative(session)
    cursor = narrative.find_cursor()
    node_addr = str(cursor.to_address())

    lock: StreamLock = request.app.state.stream_lock
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    on_token = _make_on_token(event_queue)

    def coro_fn() -> Any:
        return SectionOperator.run_end(
            session=session,
            narrative=narrative,
            llm_id=body.llm_id,
            on_token=on_token,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(lock, event_queue, session, "section", node_addr, coro_fn)


@router.post("/operator/collate")
async def operator_collate(
    body: CollateBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    from lens.core.operators.collate import CollateOperator

    narrative = _require_narrative(session)
    _validate_pins(session, body.pins, body.unpins)
    node_addr = body.address

    lock: StreamLock = request.app.state.stream_lock
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    on_token = _make_on_token(event_queue)

    def coro_fn() -> Any:
        return CollateOperator.run_collate(
            session=session,
            narrative=narrative,
            id=body.id,
            address_str=body.address,
            start_line=body.start_line,
            end_line=body.end_line,
            pins=body.pins,
            unpins=body.unpins,
            llm_id=body.llm_id,
            on_token=on_token,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(lock, event_queue, session, "collate", node_addr, coro_fn)


# ---------------------------------------------------------------------------
# Unified cancel
# ---------------------------------------------------------------------------

@router.post("/stream/cancel")
async def stream_cancel(
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> dict[str, str]:
    from lens.core.commands.rollback import execute_rollback

    lock: StreamLock = request.app.state.stream_lock
    if lock.kind is None:
        return {"status": "ok", "detail": "no stream in progress"}
    kind = lock.kind
    lock.cancel()

    # Wait briefly for the task to finish so any in-flight writes complete
    if lock.task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(lock.task), timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    # Roll back any partial changes left by the interrupted operator
    execute_rollback(session)
    session.kb.evict_tag_cache()
    return {"status": "ok", "detail": f"cancelled {kind}"}
