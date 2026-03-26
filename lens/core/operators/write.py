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
from lens.core.prompts import PromptStore, tool_prompt_key
from lens.core.tools import OperatorToolDef

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class WriteOperator(Operator):
    name: ClassVar[str] = "write"
    requires_id: ClassVar[bool] = False
    use_operator_tools: ClassVar[bool] = False

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("write.system")

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt")
        prompts = PromptStore(self.project_root)
        return prompts.format("write.instruction_with_prompt", prompt=prompt) if prompt else prompts.get("write.instruction_continue")


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

WriteOperator.register_as_tool(
    OperatorToolDef(
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Writing direction or instruction for the narrative continuation",
                },
                "kb_pin": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "KB IDs to pin for this call",
                },
                "kb_unpin": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "KB IDs to unpin for this call",
                },
            },
        },
        prompt_snippet=PromptStore(None).get(tool_prompt_key("write")),
        keep_text=True,
    )
)
