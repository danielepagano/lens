"""Helpers to mock :func:`lens.core.llm_run.run_llm` in unit tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from lens.core.generation_artifacts import GenerationArtifacts, GenerationSegment
from lens.core.llm import FinalPayload
from lens.core.llm_run import LlmRunRequest, resolve_llm_run_messages


def prose_artifacts(text: str) -> GenerationArtifacts:
    if not text:
        return GenerationArtifacts()
    return GenerationArtifacts(segments=[GenerationSegment("prose", text)])


def run_llm_from_text(
    text: str,
    *,
    on_token: Callable[[str], Awaitable[None]] | None = None,
) -> Callable[..., Awaitable[GenerationArtifacts]]:
    async def _run(request: LlmRunRequest, **kwargs: Any) -> GenerationArtifacts:
        cb = request.on_token or on_token
        if cb is not None and text:
            for chunk in text.split():
                await cb(chunk + " ")
        return prose_artifacts(text)

    return _run


def mock_run_llm(
    raw_mock: Any,
) -> Callable[..., Awaitable[GenerationArtifacts]]:
    """Adapt a callable with ``(messages, project_root, **kwargs)`` shape for ``run_llm``."""

    async def _run(request: LlmRunRequest, **kwargs: Any) -> GenerationArtifacts:
        messages = resolve_llm_run_messages(request)
        llm_kwargs: dict[str, Any] = {
            "llm_id": request.llm_id,
            "on_preview": request.on_token,
            "cancel_event": request.cancel_event,
            "reasoning": request.reasoning,
            "operator_name": request.operator_name,
            "tools": request.tools,
            "command_tool_handlers": request.command_tool_handlers,
            "interrupt_policy": request.interrupt_policy,
            "max_command_tool_iterations": request.max_command_tool_iterations,
            "stop_sequences": request.stop_sequences,
            **kwargs,
        }
        res = raw_mock(messages, request.project_root, **llm_kwargs)
        if hasattr(res, "__aiter__"):
            on_preview = request.on_token
            text = ""
            async for ev in res:
                if getattr(ev, "preview", None) and on_preview is not None:
                    await on_preview(cast(str, ev.preview))
                final = getattr(ev, "final", None)
                if final is not None:
                    if isinstance(final, FinalPayload):
                        text = final.text
                    else:
                        text = getattr(final, "text", str(final))
            return prose_artifacts(text)
        text = await cast(Awaitable[str], res)
        return prose_artifacts(text)

    return _run


def run_llm_final_from_payload(
    payload: FinalPayload,
) -> Callable[..., Awaitable[FinalPayload]]:
    async def _run(request: LlmRunRequest, **kwargs: Any) -> FinalPayload:
        cb = request.on_token
        if cb is not None and payload.text:
            for chunk in payload.text.split():
                await cb(chunk + " ")
        return payload

    return _run
