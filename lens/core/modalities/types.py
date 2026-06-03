"""Shared types for the modality registry and inline workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from collections.abc import Callable

if TYPE_CHECKING:
    from lens.core.speech.grammars import TtsGrammar
    from lens.core.speech.spec import SpeechDescriptor

from lens.core.address import NarrativeAddress
from lens.core.annotations import ParsedAnnotation
from lens.core.context import CrawlResult
from lens.core.crawl_graph import CrawlTransform
from lens.core.generation_artifacts import GenerationArtifacts
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession


@dataclass(frozen=True)
class ModalityGateResult:
    active: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class CrawlContribution:
    """Crawl-side contributions from a modality.

    ``extra_pins`` / ``extra_unpins`` are merged into :class:`~lens.core.context.CrawlSpec`
    before :func:`~lens.core.context.crawl` (see
    :func:`~lens.core.modalities.apply.merge_modality_crawl_spec`).
    ``transforms`` run after crawl via
    :func:`~lens.core.modalities.apply.apply_modality_crawl`.
    """

    transforms: tuple[CrawlTransform, ...] = ()
    extra_pins: tuple[str, ...] = ()
    extra_unpins: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandToolsContribution:
    tools: list[dict[str, Any]]
    handlers: dict[str, Any]


@dataclass(frozen=True)
class RefineApplyResult:
    text: str
    warnings: tuple[str, ...] = ()
    applied: bool = True


@dataclass(frozen=True)
class RefinePassSpec:
    """Isolated second LLM call: only ``instruction`` (+ optional system) — no crawl."""

    instruction: str
    llm_id: str | None = None
    system_message: str | None = None
    apply: Callable[[str], str | RefineApplyResult] | None = None


@dataclass(frozen=True)
class SpeechMarkupCache:
    descriptor: SpeechDescriptor
    grammar: TtsGrammar | None


@dataclass(frozen=True)
class ModalityContext:
    session: ProjectSession | None
    narrative: NarrativeNode
    focus_node: NarrativeNode
    operator_name: str
    crawl_result: CrawlResult | None
    params: dict[str, Any]
    project_root: Path
    speech_markup: SpeechMarkupCache | None = None


@dataclass(frozen=True)
class ResolvedModalities:
    active_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def active_id_set(self) -> frozenset[str]:
        return frozenset(self.active_ids)


@dataclass
class PendingInlinePersist:
    mode: Literal["start", "append"]
    cursor: NarrativeNode
    tag: str
    artifacts: GenerationArtifacts
    verbatim_prefix: str
    existing_ann: ParsedAnnotation | None
    owner: NarrativeAddress
    narrative: NarrativeNode
    operator_name: str
    refine_pass_spec: RefinePassSpec | None = None
    refine_spec_cached: bool = False
    refine_warnings: tuple[str, ...] = ()


@dataclass
class InlineGenerationResult:
    outcome: Literal["ok", "interrupted"]
    pending: PendingInlinePersist | None = None
    resolved: ResolvedModalities | None = None
    modality_context: ModalityContext | None = None
