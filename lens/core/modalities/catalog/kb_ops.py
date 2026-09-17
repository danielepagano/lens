"""Policy for the KB verbs — what the tool schemas cannot say."""

from __future__ import annotations

from lens.core.modalities.base import Modality
from lens.core.modalities.catalog._prompts import modality_prompt
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import ModalityContext


class KbOpsModality(Modality):
    """When to add versus patch, and that a failed call can simply be retried.

    The four tools carry their own mechanics in their schemas; this carries the
    judgment around them, which is the same for every operator that writes
    knowledge and would otherwise be duplicated into each one's system prompt.
    """

    id = "kb_ops"

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        return (modality_prompt(ctx, "modalities.kb_ops.rules"),)


register_modality(KbOpsModality())
