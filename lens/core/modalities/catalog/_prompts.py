"""Shared helpers for catalog modalities."""

from __future__ import annotations

from lens.core.modalities.types import ModalityContext
from lens.core.prompts import PromptStore
from lens.core.storage import Storage


def modality_prompt(ctx: ModalityContext, key: str) -> str:
    return PromptStore(ctx.project_root).get(key)


def storage_for_ctx(ctx: ModalityContext) -> Storage:
    if ctx.session is not None:
        return ctx.session.new_storage()
    return Storage(ctx.project_root)
