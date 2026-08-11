"""Shared LLM generation envelope for operators.

All operator LLM entry points go through :func:`run_llm` or
:func:`run_llm_final`. Narrative/KB generation uses :func:`run_llm`, which
returns :class:`~lens.core.generation_artifacts.GenerationArtifacts` for
composition at persist time (tool events vs prose). Tool-first single-round
flows (e.g. compress) use :func:`run_llm_final` to read native tool calls
from :class:`~lens.core.llm.FinalPayload`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lens.core.context import CrawlResult
from lens.core.generation_artifacts import GenerationArtifacts
from lens.core.modalities.types import ModalityContext, ResolvedModalities
from lens.core.llm import (
    FinalPayload,
    InterruptPolicy,
    LLMError,
    StreamEventHandler,
    apply_interrupt_policy,
    generate_artifacts,
    stream_final_payload,
)

if TYPE_CHECKING:
    from lens.core.command_tools import CommandToolFn
    from lens.core.operator import Operator

GenerateFn = Callable[..., Awaitable[GenerationArtifacts]]


@dataclass(frozen=True)
class LlmRunRequest:
    project_root: Path
    messages: list[dict[str, Any]] | None = None
    crawl_result: CrawlResult | None = None
    operator: Operator | None = None
    params: dict[str, Any] | None = None
    messages_append: tuple[dict[str, Any], ...] = ()
    llm_id: str | None = None
    reasoning: str | None = None
    operator_name: str | None = None
    interrupt_policy: InterruptPolicy = "return_empty"
    tools: list[dict[str, Any]] | None = None
    command_tool_handlers: dict[str, CommandToolFn] | None = None
    on_token: Callable[[str], Awaitable[None]] | None = None
    on_stream_event: StreamEventHandler | None = None
    cancel_event: asyncio.Event | None = None
    enable_thinking: bool | None = None
    max_command_tool_iterations: int | None = None
    stop_sequences: list[str] | None = None
    on_llm_error: Callable[[LLMError], Exception] | None = None
    resolved_modalities: ResolvedModalities | None = None
    modality_context: ModalityContext | None = None
    unlogged_tool_names: frozenset[str] = frozenset()
    """Tools whose call is not persisted as a ``tool-call`` fence — they record
    themselves in the node some other way (see :mod:`lens.core.module_requests`)."""


def resolve_llm_run_messages(request: LlmRunRequest) -> list[dict[str, Any]]:
    if request.messages is not None:
        messages = request.messages
    elif (
        request.operator is not None
        and request.crawl_result is not None
        and request.params is not None
    ):
        resolved = request.resolved_modalities
        if resolved is None:
            resolved = request.crawl_result.modality_resolution
        ctx = request.modality_context
        session = ctx.session if ctx is not None else None
        narrative = ctx.narrative if ctx is not None else None
        messages = request.operator.build_messages(
            request.crawl_result,
            request.params,
            session=session,
            narrative=narrative,
            resolved_modalities=resolved,
        )
    else:
        raise ValueError(
            "LlmRunRequest requires either messages or "
            "operator + crawl_result + params"
        )
    if request.messages_append:
        return [*messages, *request.messages_append]
    return messages


async def run_llm(
    request: LlmRunRequest,
    *,
    generate: GenerateFn = generate_artifacts,
) -> GenerationArtifacts:
    messages = resolve_llm_run_messages(request)
    return await generate(
        messages,
        request.project_root,
        llm_id=request.llm_id,
        stop_sequences=request.stop_sequences,
        tools=request.tools,
        command_tool_handlers=request.command_tool_handlers,
        cancel_event=request.cancel_event,
        enable_thinking=request.enable_thinking,
        reasoning=request.reasoning,
        operator_name=request.operator_name,
        on_preview=request.on_token,
        on_stream_event=request.on_stream_event,
        interrupt_policy=request.interrupt_policy,
        on_llm_error=request.on_llm_error,
        max_command_tool_iterations=request.max_command_tool_iterations,
        unlogged_tool_names=request.unlogged_tool_names,
    )


async def run_llm_final(request: LlmRunRequest) -> FinalPayload:
    """Single streaming round; returns full payload including tool_calls."""
    messages = resolve_llm_run_messages(request)
    try:
        final = await stream_final_payload(
            messages,
            request.project_root,
            llm_id=request.llm_id,
            stop_sequences=request.stop_sequences,
            tools=request.tools,
            cancel_event=request.cancel_event,
            command_tool_handlers=request.command_tool_handlers,
            enable_thinking=request.enable_thinking,
            reasoning=request.reasoning,
            operator_name=request.operator_name,
            on_preview=request.on_token,
            on_stream_event=request.on_stream_event,
            max_command_tool_iterations=request.max_command_tool_iterations,
            unlogged_tool_names=request.unlogged_tool_names,
        )
        return apply_interrupt_policy(final, request.interrupt_policy)
    except LLMError as e:
        if request.on_llm_error is not None:
            raise request.on_llm_error(e) from e
        raise
