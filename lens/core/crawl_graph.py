"""Structured context crawl graph primitives.

The graph is the internal representation between context collection and prompt
rendering.  It keeps text/data components annotated with source and transform
metadata so operators can add context without immediately deciding how it will
be rendered for a model.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol


ComponentKind = Literal[
    "system",
    "task",
    "knowledge",
    "reference",
    "narrative_summary",
    "current_narrative",
    "extra",
    "participant",
    "metadata",
    "warning",
]
ComponentRole = Literal[
    "system",
    "user",
    "assistant",
    "context",
    "log",
    "none",
]
SourceKind = Literal[
    "operator",
    "front_matter",
    "annotation",
    "knowledge",
    "narrative",
    "prompt",
    "transform",
    "renderer",
    "system",
]
ExpansionMode = Literal["reference", "inline", "both", "persist"]
Visibility = Literal["llm", "log", "hidden", "storage"]


def _empty_metadata() -> dict[str, str]:
    return {}


def _empty_string_list() -> list[str]:
    return []


def _empty_remember_map() -> dict[str, list[str]]:
    return {}


def _empty_vars() -> dict[str, str]:
    return {}


def _default_visibility() -> set[Visibility]:
    return {"llm"}


def _empty_components() -> list[CrawlComponent]:
    return []


def _empty_effects() -> list[RenderEffect]:
    return []


@dataclass(slots=True, frozen=True)
class ComponentSource:
    """Where a graph component came from."""

    kind: SourceKind
    identifier: str
    path: Path | None = None
    line_start: int | None = None
    line_end: int | None = None
    metadata: Mapping[str, str] = field(default_factory=_empty_metadata)


@dataclass(slots=True, frozen=True)
class ExpansionPolicy:
    """How a resolved `@` token should affect the graph."""

    mode: ExpansionMode = "reference"
    max_depth: int = 8
    persist_target_id: str | None = None


@dataclass(slots=True, frozen=True)
class RenderEffect:
    """Auditable work performed while transforming or rendering a graph."""

    kind: str
    token: str
    result: str
    source_component_id: str
    sticky: bool = False
    details: Mapping[str, str] = field(default_factory=_empty_metadata)


@dataclass(slots=True)
class CrawlComponent:
    """One ordered unit of context or renderable text."""

    id: str
    kind: ComponentKind
    text: str = ""
    role: ComponentRole = "context"
    source: ComponentSource | None = None
    visibility: set[Visibility] = field(default_factory=_default_visibility)
    priority: int = 0
    metadata: dict[str, str] = field(default_factory=_empty_metadata)
    transform_history: list[str] = field(default_factory=_empty_string_list)

    def clone_with(
        self,
        *,
        id: str | None = None,
        kind: ComponentKind | None = None,
        text: str | None = None,
        role: ComponentRole | None = None,
        source: ComponentSource | None = None,
        visibility: set[Visibility] | None = None,
        priority: int | None = None,
        metadata: Mapping[str, str] | None = None,
        transform: str | None = None,
    ) -> CrawlComponent:
        """Return a copy with selected fields updated."""

        history = list(self.transform_history)
        if transform is not None:
            history.append(transform)
        return CrawlComponent(
            id=id if id is not None else self.id,
            kind=kind if kind is not None else self.kind,
            text=text if text is not None else self.text,
            role=role if role is not None else self.role,
            source=source if source is not None else self.source,
            visibility=visibility if visibility is not None else set(self.visibility),
            priority=priority if priority is not None else self.priority,
            metadata=dict(metadata if metadata is not None else self.metadata),
            transform_history=history,
        )


@dataclass(slots=True)
class CrawlGraph:
    """Ordered context graph plus provenance and render effects."""

    project_root: Path | None = None
    components: list[CrawlComponent] = field(default_factory=_empty_components)
    effects: list[RenderEffect] = field(default_factory=_empty_effects)
    metadata: dict[str, str] = field(default_factory=_empty_metadata)
    vars: dict[str, str] = field(default_factory=_empty_vars)
    pinned_ids: list[str] = field(default_factory=_empty_string_list)
    remember_pins: dict[str, list[str]] = field(default_factory=_empty_remember_map)
    current_node_component_id: str | None = None

    def add_component(self, component: CrawlComponent) -> None:
        self.components.append(component)

    def extend_components(self, components: Iterable[CrawlComponent]) -> None:
        self.components.extend(components)

    def add_effect(self, effect: RenderEffect) -> None:
        self.effects.append(effect)

    def components_of_kind(self, kind: ComponentKind) -> list[CrawlComponent]:
        return [component for component in self.components if component.kind == kind]

    def component_by_id(self, component_id: str) -> CrawlComponent | None:
        for component in self.components:
            if component.id == component_id:
                return component
        return None

    def next_id(self, prefix: str) -> str:
        count = 1
        existing = {component.id for component in self.components}
        while f"{prefix}-{count}" in existing:
            count += 1
        return f"{prefix}-{count}"


@dataclass(slots=True, frozen=True)
class CrawlRenderResult:
    """Rendered model messages plus graph effects produced along the way."""

    messages: list[dict[str, str]]
    effects: tuple[RenderEffect, ...]


class CrawlTransform(Protocol):
    """A graph transformation pass."""

    name: str

    def apply(self, graph: CrawlGraph) -> CrawlGraph:
        """Return the transformed graph."""
        ...


class CrawlRenderer(Protocol):
    """Convert a graph into a model-specific representation."""

    name: str

    def render(self, graph: CrawlGraph) -> CrawlRenderResult:
        """Render a graph."""
        ...


def string_metadata(mapping: Mapping[str, Any] | None) -> dict[str, str]:
    """Normalize arbitrary metadata values into stable strings."""

    if not mapping:
        return {}
    return {str(key): str(value) for key, value in mapping.items()}
