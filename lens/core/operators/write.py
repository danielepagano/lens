"""Write operator: generate narrative text at the cursor node.

``lens write [PROMPT]`` streams LLM output into the cursor node and stdout,
creating a ``[write ... ]: #`` annotation that records the configuration.

When called again while owning a pending transaction:
- no arguments  → continue, appending new content to existing
- ``--retry``   → discard generated text and regenerate with same config
- prompt/pins   → discard and regenerate with updated config

``lens write --manual TEXT`` appends *TEXT* directly to the cursor node
without invoking the LLM and without adding any operator annotations.  The
result is an unstaged change (same as any other write operation) that can be
saved with ``lens commit`` or discarded with ``lens rollback``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from lens.core.operator import Operator
from lens.core.prompts import PromptStore

if TYPE_CHECKING:
    from lens.core.narrative import NarrativeNode
    from lens.core.project import ProjectSession


class WriteOperator(Operator):
    name: ClassVar[str] = "write"
    requires_id: ClassVar[bool] = False

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("write.system")

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt")
        prompts = PromptStore(self.project_root)
        return prompts.format("write.instruction_with_prompt", prompt=prompt) if prompt else prompts.get("write.instruction_continue")

    @classmethod
    def run_manual(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        text: str,
    ) -> str:
        """Append *text* directly to the cursor node without LLM or annotations.

        Returns the address of the cursor node that was written to.
        """
        storage = session.new_storage()
        cursor = narrative.find_cursor()
        op = cls(storage, narrative)
        op.append_to_node(cursor, text)
        return str(cursor.to_address())
