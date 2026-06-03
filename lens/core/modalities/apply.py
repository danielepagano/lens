"""Apply resolved modality contributions to crawl, prompts, and tools.

Hook order for a generation: resolve_modalities ``(prepare_context + gates)`` → crawl
pins merged → :func:`attach_modality_resolution_to_crawl` → ``prepare_modality_context``
(idempotent per modality) → prompt addenda / command tools → post/refine workflow.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from lens.core.context import CrawlResult, CrawlSpec, apply_transforms_to_result
from lens.core.modalities.base import Modality
from lens.core.modalities.registry import get_modality_or_raise
from lens.core.modalities.resolve import resolve_modalities
from lens.core.modalities.types import CrawlContribution, ModalityContext, ResolvedModalities
from lens.core.project import find_git_root_from


def modalities_for_resolution(resolved: ResolvedModalities) -> list[Modality]:
    return [get_modality_or_raise(mid) for mid in resolved.active_ids]


def collect_modality_crawl_contribution(
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> CrawlContribution:
    """Merge crawl contributions from all active modalities in resolution order."""
    transforms: list[Any] = []
    extra_pins: list[str] = []
    extra_unpins: list[str] = []
    for mod in modalities_for_resolution(resolved):
        contrib = mod.crawl_contributions(ctx)
        transforms.extend(contrib.transforms)
        extra_pins.extend(contrib.extra_pins)
        extra_unpins.extend(contrib.extra_unpins)
    return CrawlContribution(
        transforms=tuple(transforms),
        extra_pins=tuple(extra_pins),
        extra_unpins=tuple(extra_unpins),
    )


def _modality_project_root(spec: CrawlSpec) -> Any:
    focus = spec.node
    session = spec.session
    if session is not None:
        return session.project_root
    return find_git_root_from(focus.narrative_root.parent.parent)


def modality_context_for_spec(
    spec: CrawlSpec,
    crawl_result: CrawlResult | None = None,
) -> tuple[ModalityContext, ResolvedModalities]:
    """Build context and resolution for a spec that has ``operator`` set."""
    if crawl_result is not None:
        cached = crawl_result.modality_resolution
        base_ctx = crawl_result.modality_context
        if cached is not None and base_ctx is not None:
            ctx = replace(
                base_ctx,
                crawl_result=crawl_result,
                params=dict(spec.operator_params),
            )
            return ctx, cached

    if spec.operator is None:
        raise ValueError("modality_context_for_spec requires CrawlSpec.operator")
    focus = spec.node
    narrative = spec.narrative or focus
    params = dict(spec.operator_params)
    ctx = ModalityContext(
        session=spec.session,
        narrative=narrative,
        focus_node=focus,
        operator_name=spec.operator.name,
        crawl_result=crawl_result,
        params=params,
        project_root=_modality_project_root(spec),
    )
    resolved, prepared = resolve_modalities(spec.operator, focus, params=params, ctx=ctx)
    return prepared, resolved


def modality_context_from_crawl(
    spec: CrawlSpec,
    crawl_result: CrawlResult,
) -> tuple[ModalityContext, ResolvedModalities]:
    """Reuse resolution cached on *crawl_result* when present."""
    return modality_context_for_spec(spec, crawl_result)


def apply_operator_modalities_for_crawl(
    spec: CrawlSpec,
) -> tuple[CrawlSpec, ResolvedModalities | None, ModalityContext | None]:
    """Resolve modalities and merge pins/unpins before structural crawl."""
    if spec.operator is None:
        return spec, None, None
    ctx, resolved = modality_context_for_spec(spec, crawl_result=None)
    merged = merge_modality_crawl_spec(spec, resolved, ctx)
    return merged, resolved, ctx


def apply_operator_modalities_to_spec(spec: CrawlSpec) -> CrawlSpec:
    """Merge active modality pins/unpins into *spec* (called from :func:`~lens.core.context.crawl`)."""
    merged, _resolved, _ctx = apply_operator_modalities_for_crawl(spec)
    return merged


def prepare_modality_context(
    ctx: ModalityContext,
    resolved: ResolvedModalities,
) -> ModalityContext:
    """Run each active modality's :meth:`~lens.core.modalities.base.Modality.prepare_context`."""
    for mod in modalities_for_resolution(resolved):
        ctx = mod.prepare_context(ctx)
    return ctx


def attach_modality_resolution_to_crawl(
    crawl_result: CrawlResult,
    *,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> None:
    crawl_result.modality_resolution = resolved
    ctx = prepare_modality_context(ctx, resolved)
    crawl_result.modality_context = replace(ctx, crawl_result=crawl_result)


def merge_modality_crawl_spec(
    spec: CrawlSpec,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> CrawlSpec:
    """Return *spec* with modality ``extra_pins`` / ``extra_unpins`` folded in.

    Call before :func:`~lens.core.context.crawl` so KB resolution sees modality pins
    at the same extra level as operator-supplied extras.
    """
    contrib = collect_modality_crawl_contribution(resolved, ctx)
    if not contrib.extra_pins and not contrib.extra_unpins:
        return spec
    return replace(
        spec,
        extra_pins=spec.extra_pins + contrib.extra_pins,
        extra_unpins=spec.extra_unpins + contrib.extra_unpins,
    )


def apply_modality_crawl(
    crawl_result: CrawlResult,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> None:
    """Apply active modalities' crawl transforms to *crawl_result* in place.

    Pins and unpins must already be on the crawl spec (set ``CrawlSpec.operator`` so
    :func:`~lens.core.context.crawl` merges them before KB resolution).
    """
    contrib = collect_modality_crawl_contribution(resolved, ctx)
    if contrib.transforms:
        apply_transforms_to_result(crawl_result, list(contrib.transforms))


def apply_modality_prompt_addenda(
    messages: list[dict[str, str]],
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> list[dict[str, str]]:
    ctx = prepare_modality_context(ctx, resolved)
    addenda: list[str] = []
    for mod in modalities_for_resolution(resolved):
        addenda.extend(mod.prompt_addenda(ctx))
    if not addenda:
        return messages
    block = "\n\n".join(addenda)
    out = [dict(m) for m in messages]
    for i, msg in enumerate(out):
        if msg.get("role") == "system":
            out[i] = {"role": "system", "content": msg["content"] + block}
            break
    return out


def merge_modality_command_tools(
    tools: list[dict[str, Any]] | None,
    handlers: dict[str, Any] | None,
    resolved: ResolvedModalities,
    ctx: ModalityContext,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    merged_tools = list(tools) if tools else None
    merged_handlers = dict(handlers) if handlers else None
    for mod in modalities_for_resolution(resolved):
        contrib = mod.command_tools(ctx)
        if contrib is None:
            continue
        if merged_tools is None:
            merged_tools = []
        merged_tools.extend(contrib.tools)
        if merged_handlers is None:
            merged_handlers = {}
        merged_handlers.update(contrib.handlers)
    return merged_tools, merged_handlers
