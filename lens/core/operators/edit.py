"""Edit operator: LLM-assisted rewrite of a selected line range.

``lens edit ADDRESS START_LINE END_LINE [PROMPT] [--pin/-p ID]...`` streams
LLM output as a proposed replacement for lines START_LINE..END_LINE in the
targeted node, staging a claim annotation to track the transaction.

When called again with ``--retry``:
- no PROMPT   → regenerate with the same parameters
- PROMPT given → regenerate with updated instruction
"""

from __future__ import annotations

from typing import Any, ClassVar

from lens.core.operator import Operator
# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a skilled editor. Rewrite the provided passage following the"
    " given instructions, preserving the author's voice and style."
)

INSTRUCTION_TEMPLATE = ("Revise the following passage so it flows from the current passage, "
    " and following these instructions: '{prompt}'\nPASSAGE TO REVISE:\n{target}")


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class EditOperator(Operator):
    name: ClassVar[str] = "edit"
    requires_id: ClassVar[bool] = True

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        return INSTRUCTION_TEMPLATE.format(
            prompt=params.get("prompt", ""),
            target=params.get("target", ""),
        )
