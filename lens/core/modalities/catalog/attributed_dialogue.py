"""Attributed blockquote dialogue contract (chat, play, FM opt-in elsewhere)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lens.core.modalities.base import Modality
from lens.core.modalities.catalog._prompts import modality_prompt
from lens.core.modalities.registry import register_modality
from lens.core.modalities.types import ModalityContext

_ATTRIBUTED_DIALOGUE_LINE_RE = re.compile(
    r"^(?P<prefix>\s*(?:>\s*)*\[[^\]]+\]\s+)(?P<body>.*)$"
)


@dataclass(frozen=True, slots=True)
class AttributedDialogueSplit:
    """Prefix through the closing ``]`` of the speaker label, plus spoken body."""

    prefix: str
    body: str


def split_attributed_dialogue_line(line: str) -> AttributedDialogueSplit | None:
    """Split a line into blockquote attribution prefix and spoken body.

    Matches ``> [Name] dialogue…`` (optional leading ``>`` run). Returns ``None``
    when the line is not attributed dialogue or the body is empty after strip.
    """
    m = _ATTRIBUTED_DIALOGUE_LINE_RE.match(line)
    if m is None:
        return None
    body = m.group("body").rstrip()
    if not body:
        return None
    return AttributedDialogueSplit(prefix=m.group("prefix"), body=body)


class AttributedDialogueModality(Modality):
    id = "attributed_dialogue"

    def prompt_addenda(self, ctx: ModalityContext) -> tuple[str, ...]:
        return (modality_prompt(ctx, "modalities.attributed_dialogue.rules"),)


register_modality(AttributedDialogueModality())
