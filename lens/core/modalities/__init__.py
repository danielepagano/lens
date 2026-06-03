"""Modality registry and inline workflow hooks."""

from lens.core.modalities.apply import (
    apply_modality_crawl,
    apply_modality_prompt_addenda,
    apply_operator_modalities_for_crawl,
    apply_operator_modalities_to_spec,
    attach_modality_resolution_to_crawl,
    collect_modality_crawl_contribution,
    merge_modality_command_tools,
    merge_modality_crawl_spec,
    modality_context_for_spec,
    modality_context_from_crawl,
)
from lens.core.modalities.base import Modality
from lens.core.modalities.bootstrap import ensure_modalities_registered, reset_bootstrap_for_tests
from lens.core.modalities.registry import (
    builtin_modality_ids,
    clear_registry_for_tests,
    get_modality,
    register_modality,
    registered_ids,
)
from lens.core.modalities.resolve import resolve_modalities
from lens.core.modalities.types import (
    InlineGenerationResult,
    ModalityContext,
    PendingInlinePersist,
    RefinePassSpec,
    ResolvedModalities,
)
from lens.core.modalities.workflow import (
    apply_modality_post_refine_to_artifacts,
    run_refine_pass,
    run_workflow_post_step,
    run_workflow_refine_step,
)

__all__ = [
    "InlineGenerationResult",
    "Modality",
    "ModalityContext",
    "PendingInlinePersist",
    "RefinePassSpec",
    "ResolvedModalities",
    "apply_modality_crawl",
    "apply_modality_post_refine_to_artifacts",
    "apply_modality_prompt_addenda",
    "apply_operator_modalities_for_crawl",
    "apply_operator_modalities_to_spec",
    "attach_modality_resolution_to_crawl",
    "builtin_modality_ids",
    "collect_modality_crawl_contribution",
    "ensure_modalities_registered",
    "merge_modality_crawl_spec",
    "modality_context_for_spec",
    "modality_context_from_crawl",
    "reset_bootstrap_for_tests",
    "clear_registry_for_tests",
    "get_modality",
    "merge_modality_command_tools",
    "register_modality",
    "registered_ids",
    "resolve_modalities",
    "run_refine_pass",
    "run_workflow_post_step",
    "run_workflow_refine_step",
]
