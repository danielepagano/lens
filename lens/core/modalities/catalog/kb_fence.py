"""Design KB fenced-block output contract."""

from __future__ import annotations

from lens.core.modalities.base import Modality
from lens.core.modalities.catalog._prompts import modality_prompt
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import ModalityContext


class KbFenceModality(Modality):
    id = "kb_fence"

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        return (modality_prompt(ctx, "modalities.kb_fence.rules"),)


register_modality(KbFenceModality())
