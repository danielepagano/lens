"""Play operator: GM-voice narrative that preserves player agency.

``lens play [PROMPT]`` generates narrative in the voice of a Game Master —
describing what player characters observe, hear, and encounter — without
writing what they think, feel, decide, or do.  The operator stops at decision
or action points, giving the player space to respond.

Requires at least one knowledge object tagged ``pc`` (player character) to be
pinned in the current context, so the LLM knows who the player characters are.
"""

from __future__ import annotations

from typing import Any, ClassVar

from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operator import ContextAwareOperator, OperatorError
from lens.core.tools import OperatorToolDef
from lens.core.project import ProjectSession

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a Game Master narrating a tabletop RPG session. "
    "Write in second person or close third person, describing what the player "
    "characters observe, hear, smell, and experience in vivid detail. "
    "IMPORTANT: Do NOT write what player characters think, feel, decide, or do — "
    "their agency belongs to the player. "
    "Stop narrating when a player character faces a decision, must act, or can react. "
    "End your response at a moment that invites player input: a question, a threat, "
    "an open door, a pause before action. "
    'A player character will have a KB entry and one of its TAGS will be "pc";'
    'only characters that have a KB entry are player-controlled, for others you can decide as normal. '
)

INSTRUCTION_CONTINUE = "Continue the scene, then pause for player response."

INSTRUCTION_WITH_PROMPT = (
    "Continue the scene following these instructions: {prompt}. "
    "Then yeld to the user to allow their player(s) to act when appropriate."
)


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class PlayOperator(ContextAwareOperator):
    name: ClassVar[str] = "play"
    requires_id: ClassVar[bool] = False

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt")
        return INSTRUCTION_WITH_PROMPT.format(prompt=prompt) if prompt else INSTRUCTION_CONTINUE

    @classmethod
    def check_requirements(
        cls,
        session: ProjectSession,
        cursor: NarrativeNode,
        pins: list[str],
    ) -> None:
        """Require at least one KB object tagged ``pc`` in the current context.

        Checks explicit *pins* plus any ``kb_pin`` entries in the cursor's
        front matter.
        """
        fm_raw = cursor.front_matter().get("kb_pin", [])
        fm_pins: list[str] = (
            [p for p in fm_raw if isinstance(p, str)]  # pyright: ignore[reportUnknownVariableType]
            if isinstance(fm_raw, list) else []
        )
        all_pins = fm_pins + pins

        if not all_pins:
            raise OperatorError(
                "play requires at least one player character pinned — "
                "add a KB object tagged 'pc' with --pin or kb_pin front matter"
            )

        kb = KnowledgeStore.for_project(session.project_root)
        for pin_id in all_pins:
            base = pin_id.rstrip("!")
            if "pc" in kb.get_tags(base):
                return

        raise OperatorError(
            "play requires at least one player character (tagged 'pc') to be pinned — "
            "none of the current pins carry the 'pc' tag"
        )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

PlayOperator.register_as_tool(
    OperatorToolDef(
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Situation or scene direction for the player-facing moment",
                },
            },
        },
        prompt_snippet=(
            "Use the 'play' tool when the narrative reaches a moment that requires player "
            "agency — a decision point, an encounter, or a challenge where the player "
            "characters must act or respond. The play operator narrates in GM voice and "
            "stops for player input. Provide 'prompt' to describe the situation they face."
        ),
        keep_text=True,
    )
)
