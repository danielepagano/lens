"""Prompt `@`-token transforms before crawl/render or flat API consumers.

Three layers (do not conflate):

1. **Storable** (:class:`PromptTransformTarget.STORABLE`) — vars, inline-tag KB,
   rolls, ``@now`` on text stored in narrative/annotations or fed into ``crawl()``
   afterward. KB ``@`` mentions mostly survive for :meth:`~lens.core.operator.Operator.mention_pins`.
2. **Render** — automatic in :func:`~lens.core.context.assemble_prompt` via
   :class:`~lens.core.crawl_transforms.AtExpansionTransform` on the crawl graph.
3. **Flat** (:class:`PromptTransformTarget.FLAT`) — force-inline all ``@`` in one
   string when there is no ``crawl()`` (e.g. ``media generate``).

Graph-level transforms (modules, participants, secrets) live in
:mod:`lens.core.crawl_transforms`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from lens.core.crawl_graph import ComponentSource, CrawlComponent, CrawlGraph
from lens.core.crawl_transforms import (
    AtExpansionTransform,
    StripStandaloneMountEmbedsTransform,
    substitute_inline_kb,
    substitute_vars,
)
from lens.core.dice import substitute_rolls
from lens.core.narrative import NarrativeNode
from lens.core.now import substitute_now
from lens.core.project import get_project_locale
from lens.core.storage import Storage


class PromptTransformTarget(Enum):
    STORABLE = "storable"
    FLAT = "flat"


@dataclass(frozen=True)
class PromptTransformContext:
    project_root: Path
    storage: Storage
    cursor: NarrativeNode | None = None
    vars: dict[str, str] | None = None


def transform_prompt(
    text: str,
    ctx: PromptTransformContext,
    *,
    target: PromptTransformTarget,
) -> str:
    if target is PromptTransformTarget.STORABLE:
        return _transform_storable(text, ctx)
    if target is PromptTransformTarget.FLAT:
        return _transform_flat(text, ctx)
    raise ValueError(f"unknown prompt transform target: {target!r}")


def _resolve_vars(ctx: PromptTransformContext) -> dict[str, str]:
    if ctx.vars is not None:
        return ctx.vars
    if ctx.cursor is None:
        return {}
    from lens.core.context import collect_vars

    return collect_vars(ctx.cursor)


def _transform_storable(text: str, ctx: PromptTransformContext) -> str:
    vars_map = _resolve_vars(ctx)
    text = substitute_vars(text, vars_map)
    text = substitute_inline_kb(
        text, project_root=ctx.project_root, storage=ctx.storage
    )
    text = substitute_rolls(text)
    locale = get_project_locale(ctx.project_root)
    return substitute_now(text, locale=locale)


def _transform_flat(text: str, ctx: PromptTransformContext) -> str:
    if "@" not in text:
        return text
    graph = CrawlGraph(project_root=ctx.project_root, vars=_resolve_vars(ctx))
    graph.add_component(
        CrawlComponent(
            id="prompt-1",
            kind="task",
            text=text,
            role="user",
            source=ComponentSource(kind="prompt", identifier="pre-transform-flat"),
            visibility={"llm"},
        )
    )
    graph = AtExpansionTransform(
        project_root=ctx.project_root,
        storage=ctx.storage,
        force_inline_kb=True,
    ).apply(graph)
    graph = StripStandaloneMountEmbedsTransform().apply(graph)
    component = graph.component_by_id("prompt-1")
    return component.text if component is not None else text
