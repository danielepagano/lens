"""Builtin: Markdown fragment emit rules (no document headers)."""

from __future__ import annotations

from lens.core.modalities.base import Modality
from lens.core.modalities.catalog._prompts import modality_prompt
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import ModalityContext


class MarkdownFragmentModality(Modality):
    id = "markdown_fragment"
    builtin = True

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        return (modality_prompt(ctx, "modalities.markdown_fragment.addendum"),)


register_modality(MarkdownFragmentModality())
