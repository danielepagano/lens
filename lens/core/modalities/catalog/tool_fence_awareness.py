"""Recognize persisted ``tool-call`` fences in transcript context (design + tools)."""

from __future__ import annotations

from lens.core.modalities.base import Modality
from lens.core.modalities.catalog._prompts import modality_prompt
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import ModalityContext


class ToolFenceAwarenessModality(Modality):
    id = "tool_fence_awareness"

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        return (modality_prompt(ctx, "modalities.tool_fence_awareness.hint"),)


register_modality(ToolFenceAwarenessModality())
