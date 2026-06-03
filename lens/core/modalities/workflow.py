"""Modality post-generation workflow helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from lens.core.generation_artifacts import (
    GenerationArtifacts,
    compose_for_operator,
    replace_narrative_prose,
)
from lens.core.llm_run import LlmRunRequest, run_llm
from lens.core.modalities.registry import get_modality_or_raise
from lens.core.modalities.types import (
    ModalityContext,
    PendingInlinePersist,
    RefineApplyResult,
    RefinePassSpec,
    ResolvedModalities,
)
from lens.core.project import ProjectSession
from lens.core.workflow_runner import StepResult, WorkflowRunner, WorkflowStepDef

_log = logging.getLogger(__name__)


def modality_workflow_post_needed(resolved: ResolvedModalities) -> bool:
    for mid in resolved.active_ids:
        mod = get_modality_or_raise(mid)
        if mod.contributes_workflow_post:
            return True
    return False


def resolve_first_refine_spec(
    resolved: ResolvedModalities,
    ctx: ModalityContext,
    text: str,
) -> RefinePassSpec | None:
    for mid in resolved.active_ids:
        mod = get_modality_or_raise(mid)
        spec = mod.workflow_refine_pass(ctx, text)
        if spec is not None:
            return spec
    return None


def cache_refine_pass_spec_on_pending(
    pending: PendingInlinePersist,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> None:
    """Compute refine spec once after generate; reuse for scheduling and execution."""
    if pending.refine_spec_cached:
        return
    from lens.core.modalities.apply import prepare_modality_context

    ctx = prepare_modality_context(ctx, resolved)
    text = compose_for_operator(pending.artifacts, pending.operator_name)
    pending.refine_pass_spec = resolve_first_refine_spec(resolved, ctx, text)
    pending.refine_spec_cached = True


def apply_workflow_post_to_artifacts(
    artifacts: GenerationArtifacts,
    operator_name: str,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> None:
    text = compose_for_operator(artifacts, operator_name)
    for mid in resolved.active_ids:
        mod = get_modality_or_raise(mid)
        if mod.contributes_workflow_post:
            text = mod.workflow_post_process(ctx, text)
    replace_narrative_prose(artifacts, text)


def run_workflow_post_on_artifacts(
    pending: PendingInlinePersist,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> None:
    apply_workflow_post_to_artifacts(
        pending.artifacts, pending.operator_name, resolved, ctx
    )


def _refine_messages(spec: RefinePassSpec) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if spec.system_message:
        messages.append({"role": "system", "content": spec.system_message})
    messages.append({"role": "user", "content": spec.instruction})
    return messages


async def run_refine_pass(
    session: ProjectSession,
    spec: RefinePassSpec,
    *,
    operator_name: str,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> GenerationArtifacts:
    """Run a modality refine pass (isolated prompt; no crawl context)."""
    return await run_llm(
        LlmRunRequest(
            project_root=session.project_root,
            messages=_refine_messages(spec),
            llm_id=spec.llm_id,
            operator_name=operator_name,
            on_token=on_token,
            cancel_event=cancel_event,
        ),
    )


def _apply_refine_output(spec: RefinePassSpec, refined_text: str) -> RefineApplyResult:
    if spec.apply is None:
        return RefineApplyResult(text=refined_text, applied=True)
    out = spec.apply(refined_text)
    if isinstance(out, RefineApplyResult):
        return out
    return RefineApplyResult(text=out, applied=True)


async def apply_workflow_refine_to_artifacts(
    session: ProjectSession,
    artifacts: GenerationArtifacts,
    operator_name: str,
    spec: RefinePassSpec,
    *,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> tuple[GenerationArtifacts, tuple[str, ...]]:
    """Run refine LLM and merge; return warnings when refine had no effect."""
    warnings: list[str] = []
    refined = await run_refine_pass(
        session,
        spec,
        operator_name=operator_name,
        on_token=on_token,
        cancel_event=cancel_event,
    )
    if refined.interrupted:
        warnings.append("workflow refine: interrupted; kept pre-refine text")
        _log.warning("%s", warnings[-1])
        return artifacts, tuple(warnings)
    if not refined.has_content():
        warnings.append("workflow refine: empty model response; kept pre-refine text")
        _log.warning("%s", warnings[-1])
        return artifacts, tuple(warnings)

    refined_text = compose_for_operator(refined, operator_name)
    before = compose_for_operator(artifacts, operator_name)
    result = _apply_refine_output(spec, refined_text)
    if result.warnings:
        warnings.extend(result.warnings)
        for w in result.warnings:
            _log.warning("%s", w)
    if not result.applied:
        if not any("kept pre-refine" in w for w in warnings):
            msg = "workflow refine: no changes applied; kept pre-refine text"
            warnings.append(msg)
            _log.warning("%s", msg)
        return artifacts, tuple(warnings)
    if result.applied and result.text == before:
        return artifacts, tuple(warnings)

    replace_narrative_prose(refined, result.text)
    return refined, tuple(warnings)


async def run_modality_post_refine_workflow(
    session: ProjectSession,
    artifacts: GenerationArtifacts,
    *,
    operator_name: str,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
    workflow: WorkflowRunner | None = None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> tuple[GenerationArtifacts, tuple[str, ...]]:
    """Post-process and optional refine with the same steps as inline ``run_inline``.

    When *workflow* is set, emits ``workflow_post`` / ``workflow_refine`` steps.
    """
    pending = PendingInlinePersist(
        mode="append",
        cursor=ctx.focus_node,
        tag="",
        artifacts=artifacts,
        verbatim_prefix="",
        existing_ann=None,
        owner=ctx.focus_node.to_address(),
        narrative=ctx.narrative,
        operator_name=operator_name,
    )
    cache_refine_pass_spec_on_pending(pending, resolved, ctx)
    all_warnings: list[str] = []

    if workflow is None:
        if modality_workflow_post_needed(resolved):
            apply_workflow_post_to_artifacts(
                pending.artifacts, operator_name, resolved, ctx
            )
        if pending.refine_pass_spec is not None:
            pending.artifacts, w = await apply_workflow_refine_to_artifacts(
                session,
                pending.artifacts,
                operator_name,
                pending.refine_pass_spec,
                on_token=on_token,
                cancel_event=cancel_event,
            )
            pending.refine_warnings = w
            all_warnings.extend(w)
        return pending.artifacts, tuple(all_warnings)

    workflow.set_inline_modality_state(
        pending=pending,
        resolved=resolved,
        modality_context=ctx,
    )

    async def run_post() -> StepResult:
        return await run_workflow_post_step(
            pending=workflow.pending_inline,
            resolved=workflow.resolved_modalities,
            ctx=workflow.modality_context,
        )

    async def run_refine() -> StepResult:
        return await run_workflow_refine_step(
            session,
            pending=workflow.pending_inline,
            resolved=workflow.resolved_modalities,
            ctx=workflow.modality_context,
            on_token=on_token,
            cancel_event=cancel_event,
        )

    steps = [
        WorkflowStepDef(
            id="workflow_post",
            label="Post-processing…",
            run=run_post,
            should_run=lambda: modality_workflow_post_needed(resolved),
            failure_policy="warn",
            skippable=True,
        ),
        WorkflowStepDef(
            id="workflow_refine",
            label="Refining…",
            run=run_refine,
            should_run=lambda: pending.refine_pass_spec is not None,
            failure_policy="warn",
            skippable=True,
        ),
    ]
    outcome = await workflow.run(steps, emit_plan=False)
    for snap in outcome.steps:
        all_warnings.extend(snap.warnings)
        if snap.error:
            all_warnings.append(snap.error)
    beat_pending = workflow.pending_inline
    if beat_pending is None:
        return artifacts, tuple(all_warnings)
    all_warnings.extend(beat_pending.refine_warnings)
    return beat_pending.artifacts, tuple(all_warnings)


async def apply_modality_post_refine_to_artifacts(
    session: ProjectSession,
    artifacts: GenerationArtifacts,
    operator_name: str,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
    *,
    workflow: WorkflowRunner | None = None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> tuple[GenerationArtifacts, tuple[str, ...]]:
    """Post-process and optional refine before persist (session + inline helpers)."""
    return await run_modality_post_refine_workflow(
        session,
        artifacts,
        operator_name=operator_name,
        resolved=resolved,
        ctx=ctx,
        workflow=workflow,
        on_token=on_token,
        cancel_event=cancel_event,
    )


async def run_workflow_refine_on_artifacts(
    session: ProjectSession,
    pending: PendingInlinePersist,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
    *,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> tuple[str, ...]:
    if pending.refine_pass_spec is None:
        return ()
    pending.artifacts, warnings = await apply_workflow_refine_to_artifacts(
        session,
        pending.artifacts,
        pending.operator_name,
        pending.refine_pass_spec,
        on_token=on_token,
        cancel_event=cancel_event,
    )
    pending.refine_warnings = warnings
    return warnings


async def run_workflow_post_step(
    *,
    pending: PendingInlinePersist | None,
    resolved: ResolvedModalities | None,
    ctx: ModalityContext | None,
) -> StepResult:
    if pending is None or resolved is None or ctx is None:
        return StepResult(ok=True, skipped=True)
    if not modality_workflow_post_needed(resolved):
        return StepResult(ok=True, skipped=True)
    try:
        run_workflow_post_on_artifacts(pending, resolved, ctx)
        return StepResult(ok=True)
    except Exception as e:
        return StepResult(ok=False, error=str(e))


async def run_workflow_refine_step(
    session: ProjectSession,
    *,
    pending: PendingInlinePersist | None,
    resolved: ResolvedModalities | None,
    ctx: ModalityContext | None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> StepResult:
    if pending is None or resolved is None or ctx is None:
        return StepResult(ok=True, skipped=True)
    if pending.refine_pass_spec is None:
        return StepResult(ok=True, skipped=True)
    try:
        warnings = await run_workflow_refine_on_artifacts(
            session,
            pending,
            resolved,
            ctx,
            on_token=on_token,
            cancel_event=cancel_event,
        )
        if warnings:
            return StepResult(ok=True, warnings=tuple(warnings))
        return StepResult(ok=True)
    except Exception as e:
        return StepResult(ok=False, error=str(e))
