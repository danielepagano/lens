"""Resolve active modalities for an operator at a focus node."""

from __future__ import annotations

from typing import Any, cast

from lens.core.modalities.registry import (
    builtin_modality_ids,
    get_modality,
    get_modality_or_raise,
)
from lens.core.modalities.types import ModalityContext, ResolvedModalities
from lens.core.narrative import NarrativeNode
from lens.core.pinning import collect_modalities_fm, modality_enabled
from lens.core.project import find_git_root_from


def _topological_order(ids: frozenset[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(modality_id: str) -> None:
        if modality_id in visited:
            return
        if modality_id in visiting:
            return
        visiting.add(modality_id)
        mod = get_modality_or_raise(modality_id)
        for dep in sorted(mod.dependencies()):
            if dep in ids:
                visit(dep)
        visiting.remove(modality_id)
        visited.add(modality_id)
        ordered.append(modality_id)

    for mid in sorted(ids):
        visit(mid)
    return tuple(ordered)


def _filter_registered(
    candidate_ids: set[str],
) -> tuple[set[str], list[str]]:
    """Keep only registered modality ids; warn on unknown names."""
    active: set[str] = set()
    warnings: list[str] = []
    for modality_id in sorted(candidate_ids):
        if get_modality(modality_id) is None:
            warnings.append(f"unknown modality {modality_id!r}")
            continue
        active.add(modality_id)
    return active, warnings


def resolve_modalities(
    operator_cls: type[Any],
    focus_node: NarrativeNode,
    *,
    params: dict[str, Any] | None = None,
    default_ids: frozenset[str] | None = None,
    extra_required: frozenset[str] | None = None,
    ctx: ModalityContext | None = None,
) -> tuple[ResolvedModalities, ModalityContext]:
    """Resolve active modalities and return prepared context.

    Built-in modalities (``Modality.builtin``) are on by default; FM
    ``modalities.<id>: false`` (or ``modalities.<id>.enabled: false``) opts
    out. *default_ids* is for tests only.

    Returns ``(resolved, gate_ctx)`` where *gate_ctx* is the :class:`ModalityContext`
    after :meth:`~lens.core.modalities.base.Modality.prepare_context` and
    :meth:`~lens.core.modalities.base.Modality.gates` for each candidate id in
    topological order (including modalities that gate off).
    """
    candidate: set[str] = set(default_ids or ())
    candidate.update(builtin_modality_ids())
    fm_configs = collect_modalities_fm(focus_node)
    for key, config in fm_configs.items():
        if modality_enabled(config):
            candidate.add(key)
        else:
            candidate.discard(key)

    required = cast(
        frozenset[str],
        getattr(operator_cls, "required_modalities", frozenset[str]()),
    )
    candidate.update(required)

    if params is not None and hasattr(operator_cls, "extra_required_modalities"):
        extra = operator_cls.extra_required_modalities(params)
        candidate.update(extra)

    if extra_required:
        candidate.update(extra_required)

    active, warnings = _filter_registered(candidate)

    expanded: set[str] = set(active)
    for modality_id in list(active):
        mod = get_modality_or_raise(modality_id)
        for dep in mod.dependencies():
            if get_modality(dep) is not None:
                expanded.add(dep)
    expanded.update(active)

    expanded, expand_warnings = _filter_registered(expanded)
    warnings.extend(expand_warnings)

    ordered = _topological_order(frozenset(expanded))
    active_ids: list[str] = []
    gate_ctx = ctx
    if gate_ctx is None:
        try:
            project_root = find_git_root_from(focus_node.md_path())
        except (FileNotFoundError, ValueError):
            project_root = focus_node.narrative_root
        gate_ctx = ModalityContext(
            session=None,
            narrative=focus_node,
            focus_node=focus_node,
            operator_name=str(getattr(operator_cls, "name", "")),
            crawl_result=None,
            params=dict(params or {}),
            project_root=project_root,
        )

    for modality_id in ordered:
        mod = get_modality_or_raise(modality_id)
        gate_ctx = mod.prepare_context(gate_ctx)
        gate = mod.gates(gate_ctx)
        if not gate.active:
            if gate.reason:
                warnings.append(f"{modality_id}: {gate.reason}")
            else:
                warnings.append(f"{modality_id}: gated off")
            continue
        active_ids.append(modality_id)

    return (
        ResolvedModalities(active_ids=tuple(active_ids), warnings=tuple(warnings)),
        gate_ctx,
    )
