"""AI operator execution over HTTP with SSE streaming."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lens.core.compression import Aggressiveness
from lens.core.commands.pin import resolve_node
from lens.core.commands.rollback import execute_rollback
from lens.core.exceptions import OperatorError, LensException, ValidationError
from lens.core.knowledge import validate_ids_exist
from lens.core.now import set_request_timezone
from lens.core.operator_params import chat_invocation_uses_session, prepare_chat_invocation
from lens.core.storage import Storage
from lens.core.llm import llm_progress_scope
from lens.core.project import ProjectSession
from lens.core.workflow_runner import WorkflowOutcome, WorkflowRunner, current_workflow_step_id
from lens.server.dependencies import get_session, get_stream_lock
from lens.server.streaming import StreamLock, operator_stream_response

router = APIRouter(prefix="/{project_slug}")
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class WriteBody(BaseModel):
    prompt: str | None = None
    pins: list[str] = []
    unpins: list[str] = []
    mentions: list[str] = []
    includes: list[str] = []
    llm_id: str | None = None
    reasoning: str | None = None
    retry: bool = False


class WriteManualBody(BaseModel):
    text: str


class PlayBody(BaseModel):
    prompt: str | None = None
    module_id: str | None = None
    module_ids: list[str] | None = None
    pins: list[str] = []
    unpins: list[str] = []
    mentions: list[str] = []
    includes: list[str] = []
    llm_id: str | None = None
    reasoning: str | None = None
    retry: bool = False
    end: bool = False
    as_pc: str | None = None
    do_pass: bool = False
    slug: str | None = None


class DesignBody(BaseModel):
    prompt: str | None = None
    module_id: str | None = None
    module_ids: list[str] | None = None
    pins: list[str] = []
    unpins: list[str] = []
    mentions: list[str] = []
    includes: list[str] = []
    llm_id: str | None = None
    reasoning: str | None = None
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
    reasoning: str | None = None
    retry: bool = False
    replace: bool = False


class SectionStartBody(BaseModel):
    id: str
    pins: list[str] = []
    unpins: list[str] = []


class SectionEndBody(BaseModel):
    llm_id: str | None = None
    reasoning: str | None = None
    summary_guide: str | None = None


class AdvanceBody(BaseModel):
    days: int = 1
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    reasoning: str | None = None
    retry: bool = False
    feedback: str | None = None
    end: bool = False


class ChatBody(BaseModel):
    prompt: str | None = None
    as_kb_id: str | None = None
    with_kb_id: str | None = None
    narrate: bool | None = None
    wait: bool | None = None
    pins: list[str] = []
    unpins: list[str] = []
    mentions: list[str] = []
    includes: list[str] = []
    llm_id: str | None = None
    reasoning: str | None = None
    retry: bool = False
    end: bool = False
    slug: str | None = None


class CollateBody(BaseModel):
    id: str
    address: str
    start_line: int
    end_line: int
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    reasoning: str | None = None
    summary_guide: str | None = None


class CompressBody(BaseModel):
    prompt: str | None = None
    aggressiveness: Aggressiveness | None = None
    address: str | None = None  # narrative node (display form); default cursor
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    reasoning: str | None = None
    summary_guide: str | None = None


class WorkflowActionBody(BaseModel):
    step_id: str
    action: str  # "retry" | "skip" | "cancel"


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


def _validate_pins(
    session: ProjectSession,
    pins: list[str],
    unpins: list[str],
    scoped: list[str] | None = None,
) -> None:
    try:
        validate_ids_exist(session.project_root, pins + unpins + list(scoped or []))
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _body_module_keys(
    module_id: str | None, module_ids: list[str] | None
) -> list[str]:
    """Merge a request's module fields into the operator's ordered key list.

    ``module_id`` is the original single-module field, kept so existing clients
    keep working; ``module_ids`` is the list form.  A client may send either,
    and one that sends both gets them in that order with duplicates collapsed.
    """
    keys: list[str] = []
    for raw in [module_id, *(module_ids or [])]:
        if not isinstance(raw, str):
            continue
        key = raw.strip()
        if key and key not in keys:
            keys.append(key)
    return keys


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
        step_id = current_workflow_step_id()
        if step_id is not None:
            payload["step_id"] = step_id
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
                    if isinstance(result, WorkflowOutcome):
                        done_payload["workflow_outcome"] = result.kind
                        done_payload["steps"] = [
                            {
                                "id": s.id,
                                "label": s.label,
                                "status": s.status,
                                **({"error": s.error} if s.error else {}),
                                **({"warnings": list(s.warnings)} if s.warnings else {}),
                                **({"skippable": True} if s.skippable else {}),
                            }
                            for s in result.steps
                        ]
                        if result.interrupted:
                            done_payload["interrupted"] = True
                        if result.rollback_pending:
                            done_payload["rollback_pending"] = True
                    elif isinstance(result, Storage):
                        pass
                    # Design returns KbExtractResult
                    elif hasattr(result, "inserted"):
                        done_payload["inserted"] = result.inserted
                        done_payload["updated"] = result.updated
                        done_payload["errors"] = result.errors
                    # Section end returns key string
                    elif isinstance(result, str):
                        done_payload["section_key"] = result
                await event_queue.put(done_payload)
            except ValidationError as e:
                _log.warning("operator %s validation error: %s", operator_name, e)
                await event_queue.put({"type": "error", "message": str(e)})
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
        payload: dict[str, Any] = {"type": "token", "text": chunk}
        step_id = current_workflow_step_id()
        if step_id is not None:
            payload["step_id"] = step_id
        await event_queue.put(payload)
    return on_token


def _make_on_stream_event(
    event_queue: asyncio.Queue[dict[str, Any] | None],
) -> Any:
    """Create a callback that pushes structured stream events (e.g. tool_call) to the SSE queue."""
    async def on_stream_event(event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "tool_call":
            sse: dict[str, Any] = {"type": "tool_call"}
            if "name" in payload:
                sse["name"] = payload["name"]
            if "summary" in payload:
                sse["summary"] = payload["summary"]
            await event_queue.put(sse)
    return on_stream_event


def _make_on_workflow_event(
    event_queue: asyncio.Queue[dict[str, Any] | None],
) -> Any:
    async def on_workflow_event(payload: dict[str, Any]) -> None:
        await event_queue.put(payload)

    return on_workflow_event


def _init_stream(
    request: Request,
    session: ProjectSession,
    lock: StreamLock,
) -> tuple[Any, StreamLock, asyncio.Queue[dict[str, Any] | None], Any, Any]:
    """Set timezone context, validate narrative exists, return (narrative, lock, event_queue, on_token, on_stream_event)."""
    set_request_timezone(request.headers.get("Time-Zone"))
    narrative = _require_narrative(session)
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    on_token = _make_on_token(event_queue)
    on_stream_event = _make_on_stream_event(event_queue)
    return narrative, lock, event_queue, on_token, on_stream_event


def _start_operator_stream(
    lock: StreamLock,
    event_queue: asyncio.Queue[dict[str, Any] | None],
    session: ProjectSession,
    operator_name: str,
    node_address: str | Callable[[], str],
    coro_fn: Any,
    request: Request,
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

    lock.workflow = WorkflowRunner(
        session=session,
        cancel_event=lock.cancel_event,
        on_event=_make_on_workflow_event(event_queue),
    )

    task = asyncio.ensure_future(
        _run_operator_task(
            coro_fn, event_queue, operator_name, node_address, session,
        )
    )
    lock.task = task

    return operator_stream_response(event_queue, lock, request, session)


# ---------------------------------------------------------------------------
# Operator endpoints
# ---------------------------------------------------------------------------

@router.post("/operator/write")
async def operator_write(
    body: WriteBody,
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.core.operators.write import WriteOperator

    narrative, lock, event_queue, on_token, _on_se = _init_stream(request, session, lock)
    _validate_pins(session, body.pins, body.unpins, body.mentions + body.includes)
    cursor = narrative.find_cursor()
    node_addr = str(cursor.to_address())

    def coro_fn() -> Any:
        return _write_coro()

    async def _write_coro() -> Any:
        return await WriteOperator.run_inline(
            session=session,
            narrative=narrative,
            prompt=body.prompt,
            pins=body.pins,
            unpins=body.unpins,
            mentions=body.mentions,
            includes=body.includes,
            llm_id=body.llm_id,
            reasoning=body.reasoning,
            retry=body.retry,
            on_token=on_token,
            cancel_event=lock.cancel_event,
            on_info_event=event_queue.put,
            workflow=lock.workflow,
        )

    return _start_operator_stream(lock, event_queue, session, "write", node_addr, coro_fn, request)


@router.post("/operator/write/manual")
async def operator_write_manual(
    body: WriteManualBody,
    project_slug: str,
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
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.rpg.operators.play import PlayOperator

    narrative, lock, event_queue, on_token, _on_se = _init_stream(request, session, lock)
    pins = list(body.pins)
    unpins = list(body.unpins)
    scoped = list(body.mentions) + list(body.includes)
    module_keys = _body_module_keys(body.module_id, body.module_ids)
    if module_keys:
        pins_for_validation = pins + [f"rules.{key}" for key in module_keys]
        _validate_pins(session, pins_for_validation, unpins, scoped)
    else:
        _validate_pins(session, pins, unpins, scoped)
    pins = _play_pins_with_encounter_expand(pins)
    cursor = narrative.find_cursor()
    target_ref: list[str] = [str(cursor.to_address())]

    async def on_stream_target(addr: str) -> None:
        target_ref[0] = addr
        await event_queue.put({"type": "target", "node": addr})

    extra_params: dict[str, Any] | None = None
    if body.as_pc is not None or body.do_pass:
        extra_params = {}
        if body.as_pc is not None:
            extra_params["as_pc"] = body.as_pc
        if body.do_pass:
            extra_params["pass"] = True

    def coro_fn() -> Any:
        return _play_coro()

    async def _play_coro() -> Any:
        return await PlayOperator.run_session(
            session=session,
            narrative=narrative,
            prompt=body.prompt,
            module_ids=module_keys,
            pins=pins,
            unpins=unpins,
            mentions=body.mentions,
            includes=body.includes,
            llm_id=body.llm_id,
            reasoning=body.reasoning,
            retry=body.retry,
            end=body.end,
            slug=body.slug if not body.end and not body.retry else None,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=lock.cancel_event,
            on_info_event=event_queue.put,
            extra_params=extra_params,
            workflow=lock.workflow,
        )

    return _start_operator_stream(
        lock, event_queue, session, "play", lambda: target_ref[0], coro_fn, request
    )


@router.post("/operator/advance")
async def operator_advance(
    body: AdvanceBody,
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.rpg.operators.advance import AdvanceOperator

    narrative, lock, event_queue, on_token, _on_se = _init_stream(request, session, lock)
    _validate_pins(session, body.pins, body.unpins)
    cursor = narrative.find_cursor()
    target_ref: list[str] = [str(cursor.to_address())]

    async def on_stream_target(addr: str) -> None:
        target_ref[0] = addr
        await event_queue.put({"type": "target", "node": addr})

    def coro_fn() -> Any:
        return AdvanceOperator.run_advance(
            session=session,
            narrative=narrative,
            increment=body.days,
            pins=body.pins,
            unpins=body.unpins,
            llm_id=body.llm_id,
            reasoning=body.reasoning,
            retry=body.retry,
            feedback=body.feedback,
            end=body.end,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(
        lock, event_queue, session, "advance", lambda: target_ref[0], coro_fn, request
    )


@router.post("/operator/design")
async def operator_design(
    body: DesignBody,
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.core.operators.design import DesignOperator

    narrative, lock, event_queue, on_token, on_stream_event = _init_stream(request, session, lock)
    pins = list(body.pins)
    unpins = list(body.unpins)
    scoped = list(body.mentions) + list(body.includes)
    module_keys = _body_module_keys(body.module_id, body.module_ids)
    if module_keys:
        pins_for_validation = pins + [f"design.{key}" for key in module_keys]
        _validate_pins(session, pins_for_validation, unpins, scoped)
    else:
        _validate_pins(session, pins, unpins, scoped)
    cursor = narrative.find_cursor()
    target_ref: list[str] = [str(cursor.to_address())]

    async def on_stream_target(addr: str) -> None:
        target_ref[0] = addr
        await event_queue.put({"type": "target", "node": addr})

    def coro_fn() -> Any:
        return DesignOperator.run_design(
            session=session,
            narrative=narrative,
            prompt=body.prompt,
            module_ids=module_keys,
            pins=pins,
            unpins=unpins,
            mentions=body.mentions,
            includes=body.includes,
            llm_id=body.llm_id,
            reasoning=body.reasoning,
            retry=body.retry,
            end=body.end,
            slug=body.slug if not body.end and not body.retry else None,
            on_token=on_token,
            on_stream_target=on_stream_target,
            on_stream_event=on_stream_event,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(
        lock, event_queue, session, "design", lambda: target_ref[0], coro_fn, request
    )



@router.post("/operator/chat")
async def operator_chat(
    body: ChatBody,
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.core.operators.chat import ChatOperator

    narrative, lock, event_queue, on_token, _on_se = _init_stream(request, session, lock)
    pins = list(body.pins)
    unpins = list(body.unpins)
    session_node, _ = ChatOperator.find_active_session(narrative)
    cursor = narrative.find_cursor()
    target_ref: list[str] = [str(cursor.to_address())]

    extra_params: dict[str, Any] = {}
    if body.as_kb_id is not None:
        extra_params["as_kb_id"] = body.as_kb_id
    if body.with_kb_id is not None:
        extra_params["with_kb_id"] = body.with_kb_id
    if body.narrate is not None:
        extra_params["narrate"] = body.narrate
    if body.wait is not None:
        extra_params["wait"] = body.wait

    eff_llm_id, eff_reasoning, merged_chat_extra = prepare_chat_invocation(
        session,
        narrative,
        llm_id=body.llm_id,
        reasoning=body.reasoning,
        extra_params=extra_params,
    )
    extra_params_arg: dict[str, Any] | None = (
        merged_chat_extra if merged_chat_extra else None
    )

    validate_kb_ids = list(pins)
    ak = merged_chat_extra.get("as_kb_id")
    wk = merged_chat_extra.get("with_kb_id")
    if isinstance(ak, str):
        validate_kb_ids.append(ak)
    if isinstance(wk, str):
        validate_kb_ids.append(wk)
    _validate_pins(
        session, validate_kb_ids, unpins, list(body.mentions) + list(body.includes)
    )

    async def on_stream_target(addr: str) -> None:
        target_ref[0] = addr
        await event_queue.put({"type": "target", "node": addr})

    if chat_invocation_uses_session(end=body.end, extra_params=merged_chat_extra):

        async def _chat_session_explicit() -> Any:
            return await ChatOperator.run_session(
                session=session,
                narrative=narrative,
                prompt=body.prompt,
                module_ids=None,
                pins=pins,
                unpins=unpins,
                mentions=body.mentions,
                includes=body.includes,
                llm_id=eff_llm_id,
                reasoning=eff_reasoning,
                retry=body.retry,
                end=body.end,
                slug=body.slug if not body.end and not body.retry else None,
                on_token=on_token,
                on_stream_target=on_stream_target,
                cancel_event=lock.cancel_event,
                on_info_event=event_queue.put,
                extra_params=extra_params_arg,
                workflow=lock.workflow,
            )

        def coro_fn() -> Any:
            return _chat_session_explicit()

    elif session_node is not None:

        async def _chat_session_continue() -> Any:
            return await ChatOperator.run_session(
                session=session,
                narrative=narrative,
                prompt=body.prompt,
                module_ids=None,
                pins=pins,
                unpins=unpins,
                mentions=body.mentions,
                includes=body.includes,
                llm_id=eff_llm_id,
                reasoning=eff_reasoning,
                retry=body.retry,
                end=False,
                slug=None,
                on_token=on_token,
                on_stream_target=on_stream_target,
                cancel_event=lock.cancel_event,
                on_info_event=event_queue.put,
                extra_params=extra_params_arg,
                workflow=lock.workflow,
            )

        def coro_fn() -> Any:
            return _chat_session_continue()

    else:

        async def _chat_inline() -> Any:
            return await ChatOperator.run_inline(
                session=session,
                narrative=narrative,
                prompt=body.prompt,
                pins=pins,
                unpins=unpins,
                mentions=body.mentions,
                includes=body.includes,
                llm_id=eff_llm_id,
                reasoning=eff_reasoning,
                retry=body.retry,
                on_token=on_token,
                cancel_event=lock.cancel_event,
                on_info_event=event_queue.put,
                extra_params=extra_params_arg,
                workflow=lock.workflow,
            )

        def coro_fn() -> Any:
            return _chat_inline()

    return _start_operator_stream(
        lock, event_queue, session, "chat", lambda: target_ref[0], coro_fn, request
    )


@router.post("/operator/edit")
async def operator_edit(
    body: EditBody,
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.core.address import NarrativeAddress
    from lens.core.operators.edit import EditOperator
    from lens.core.project import resolve_address

    _, lock, event_queue, on_token, _on_se = _init_stream(request, session, lock)
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
            reasoning=body.reasoning,
            retry=body.retry,
            on_token=on_token,
            cancel_event=lock.cancel_event,
        )

    return _start_operator_stream(lock, event_queue, session, "edit", node_addr, coro_fn, request)


@router.post("/operator/section/start")
async def operator_section_start(
    body: SectionStartBody,
    project_slug: str,
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
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.core.operators.section import SectionOperator

    narrative, lock, event_queue, on_token, _on_se = _init_stream(request, session, lock)
    cursor = narrative.find_cursor()
    node_addr = str(cursor.to_address())

    async def _section_end_coro() -> Any:
        return await SectionOperator.run_end(
            session=session,
            narrative=narrative,
            llm_id=body.llm_id,
            reasoning=body.reasoning,
            on_token=on_token,
            cancel_event=lock.cancel_event,
            summary_guidance=(body.summary_guide or "").strip() or None,
            workflow=lock.workflow,
        )

    def coro_fn() -> Any:
        return _section_end_coro()

    return _start_operator_stream(lock, event_queue, session, "section", node_addr, coro_fn, request)


@router.post("/operator/collate")
async def operator_collate(
    body: CollateBody,
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.core.operators.collate import CollateOperator

    narrative, lock, event_queue, on_token, _on_se = _init_stream(request, session, lock)
    _validate_pins(session, body.pins, body.unpins)
    node_addr = body.address

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
            reasoning=body.reasoning,
            on_token=on_token,
            cancel_event=lock.cancel_event,
            summary_guidance=(body.summary_guide or "").strip() or None,
            workflow=lock.workflow,
        )

    return _start_operator_stream(lock, event_queue, session, "collate", node_addr, coro_fn, request)


@router.post("/operator/compress")
async def operator_compress(
    body: CompressBody,
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    from lens.core.operators.compress import CompressNoCollate, run_compress

    narrative, lock, event_queue, on_token, _on_se = _init_stream(request, session, lock)
    _validate_pins(session, body.pins, body.unpins)
    try:
        target = resolve_node(session, (body.address or "").strip() or None)
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    node_addr = str(target.to_address())

    async def _compress_coro() -> Any:
        r = await run_compress(
            session=session,
            narrative=narrative,
            prompt=body.prompt,
            aggressiveness=body.aggressiveness,
            address=body.address,
            pins=body.pins,
            unpins=body.unpins,
            llm_id=body.llm_id,
            reasoning=body.reasoning,
            summary_guide=body.summary_guide,
            on_token=on_token,
            cancel_event=lock.cancel_event,
            workflow=lock.workflow,
        )
        if isinstance(r, CompressNoCollate):
            raise ValidationError(r.explanation or "compress: model did not select a range to collate")
        return r

    def coro_fn() -> Any:
        return _compress_coro()

    return _start_operator_stream(lock, event_queue, session, "compress", node_addr, coro_fn, request)


# ---------------------------------------------------------------------------
# Unified cancel
# ---------------------------------------------------------------------------

@router.post("/stream/cancel")
async def stream_cancel(
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> dict[str, str]:
    if lock.kind is None:
        return {"status": "ok", "detail": "no stream in progress"}
    kind = lock.kind
    lock.cancel()

    if lock.task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(lock.task), timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    session.kb.evict_tag_cache()
    return {"status": "ok", "detail": f"cancelled {kind}"}


@router.post("/stream/workflow/action")
async def stream_workflow_action(
    body: WorkflowActionBody,
    project_slug: str,
    lock: StreamLock = Depends(get_stream_lock),
) -> dict[str, str]:
    if lock.kind is None or lock.workflow is None:
        raise HTTPException(status_code=400, detail="no workflow stream in progress")
    if body.action not in ("retry", "skip", "cancel"):
        raise HTTPException(
            status_code=400, detail="action must be retry, skip or cancel"
        )
    try:
        if body.action == "cancel":
            # Step-scoped: stops that step only, leaving earlier steps' work intact.
            lock.workflow.cancel_step(body.step_id)
        else:
            lock.workflow.signal_action(body.step_id, body.action)  # type: ignore[arg-type]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "ok", "step_id": body.step_id, "action": body.action}
