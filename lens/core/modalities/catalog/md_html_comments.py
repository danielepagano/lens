"""Builtin: ``ai:`` and ``ai:secret:`` HTML comment conventions."""

from __future__ import annotations

from lens.core.modalities.base import Modality
from lens.core.modalities.catalog._prompts import modality_prompt
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import ModalityContext


class MdHtmlCommentsModality(Modality):
    id = "md_html_comments"
    builtin = True

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        return (modality_prompt(ctx, "modalities.md_html_comments.rules"),)


register_modality(MdHtmlCommentsModality())
