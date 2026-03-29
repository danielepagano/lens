"""Write operator: generate narrative text at the cursor node.

``lens write [PROMPT]`` streams LLM output into the cursor node and stdout,
creating a ``[write ... ]: #`` annotation that records the configuration.

When called again while owning a pending transaction:
- no arguments  → continue, appending new content to existing
- ``--retry``   → discard generated text and regenerate with same config
- prompt/pins   → discard and regenerate with updated config
"""

from __future__ import annotations

from typing import Any, ClassVar

from lens.core.operator import Operator
from lens.core.prompts import PromptStore


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
