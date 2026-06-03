"""Modality base class: set ``id`` and override only the hooks you need."""

from __future__ import annotations

from abc import ABC

from lens.core.modalities.types import (
    CommandToolsContribution,
    CrawlContribution,
    ModalityContext,
    ModalityGateResult,
    RefinePassSpec,
)


class Modality(ABC):
    """Hook-based plugin for LLM-facing behavior on an operator run.

    **Activation** is not done here. :func:`~lens.core.modalities.resolve.resolve_modalities`
    builds the active set from: registered ``builtin`` modalities (unless FM opts
    out), front matter ``modalities:`` (root → cursor), ``operator.required_modalities``,
    and ``extra_required_modalities(params)``. Only registered ids are kept;
    unknown names produce warnings on :class:`~lens.core.modalities.types.ResolvedModalities`.

    **Registration** (:func:`~lens.core.modalities.registry.register_modality`) only
    stores implementations in a lookup table. Nothing runs because something was
    registered; hooks run when an id is *resolved active* for that generation.

    Subclasses must set ``id`` (class attribute). Unoverridden hooks are no-ops.

    Set ``builtin = True`` when the modality should be on by default (unless FM
    sets ``modalities.<id>: false``). Register with
    :func:`~lens.core.modalities.registry.register_modality` at module import.
    """

    id: str
    builtin: bool = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if ABC in cls.__bases__:
            return
        mid = getattr(cls, "id", None)
        if not isinstance(mid, str) or not mid:
            raise TypeError(f"{cls.__name__} must define a non-empty id: str class attribute")

    @property
    def contributes_workflow_post(self) -> bool:
        """When ``True``, the inline workflow runs the ``workflow_post`` step.

        That step chains :meth:`workflow_post_process` over composed generation text
        before persist. You must set this to ``True`` when overriding
        :meth:`workflow_post_process`; overriding the method alone does nothing.
        """
        return False

    def dependencies(self) -> frozenset[str]:
        """Other modality ids that must be active whenever this one is.

        Resolved ids are expanded and topologically ordered before :meth:`gates` runs.
        Dependents are not auto-registered; each dependency must be registered and
        activated via defaults, FM, or operator requirements.
        """
        return frozenset()

    def prepare_context(self, ctx: ModalityContext) -> ModalityContext:
        """Load or cache per-run state on *ctx* before other hooks.

        Called in resolution order for each candidate modality (before :meth:`gates`)
        and again when applying crawl / prompt / refine helpers. Return an updated
        context; default is unchanged. Implementations should be idempotent.
        """
        return ctx

    def gates(self, ctx: ModalityContext) -> ModalityGateResult:
        """Per-run eligibility after static resolution.

        Called for each candidate id (with a built :class:`ModalityContext` if the
        caller did not supply one). Return ``active=False`` to drop this modality for
        this run; a reason is appended to resolution warnings.
        """
        del ctx
        return ModalityGateResult()

    def crawl_contributions(self, ctx: ModalityContext) -> CrawlContribution:
        """Extra crawl inputs for this generation.

        Pins and unpins are merged into :class:`~lens.core.context.CrawlSpec` before
        :func:`~lens.core.context.crawl`; graph transforms run afterward in
        :func:`~lens.core.modalities.apply.apply_modality_crawl`.
        """
        del ctx
        return CrawlContribution()

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        """Extra system-prompt fragments, concatenated in resolution order.

        Injected in :func:`~lens.core.modalities.apply.apply_modality_prompt_addenda`
        onto the system message after :func:`~lens.core.context.assemble_prompt`
        (which still owns shared formatting keys until ported).
        """
        del ctx
        return ()

    def command_tools(self, ctx: ModalityContext) -> CommandToolsContribution | None:
        """Optional inline command tools merged into the generation request.

        Merged in :func:`~lens.core.modalities.apply.merge_modality_command_tools`
        with the operator's base tool bundle. Return ``None`` when this modality
        adds no tools.
        """
        del ctx
        return None

    def workflow_post_process(self, ctx: ModalityContext, text: str) -> str:
        """Deterministic post-processing of composed prose before persist.

        Chained in registration order during the ``workflow_post`` step. Receives
        composed operator text (prose + tool fences per compose policy); return the
        text to persist.
        """
        del ctx
        return text

    def workflow_refine_pass(self, ctx: ModalityContext, text: str) -> RefinePassSpec | None:
        """Optional second LLM pass after post-processing.

        Return a spec to run :func:`~lens.core.modalities.workflow.run_refine_pass`
        during ``workflow_refine`` (first non-``None`` spec among active modalities wins).
        The refine LLM sees only ``RefinePassSpec.instruction`` — not crawl context.
        Also consulted when deciding whether ``workflow_refine`` should appear in the
        plan, so this method may run even if the user skips that step. Return ``None``
        to decline a refine pass.
        """
        del ctx, text
        return None
