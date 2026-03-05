"""Play operator: GM-voice narrative that preserves player agency.

``lens play [PROMPT]`` generates narrative in the voice of a Game Master —
describing what player characters observe, hear, and encounter — without
writing what they think, feel, decide, or do.  The operator stops at decision
or action points, giving the player space to respond.

Requires ``rules.dnd`` and ``rules.engagement`` to be pinned (they carry the
full ruleset and the player-AI contract), plus at least one ``pc.*`` KB object
so the LLM knows who the player characters are.
"""

from __future__ import annotations

from typing import Any, ClassVar

from lens.core.narrative import NarrativeNode
from lens.core.operator import Operator, OperatorError
from lens.core.project import ProjectSession
from lens.core.tools import OperatorToolDef

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the Game Master. "
    "The Rules of Engagement are pinned in your context — follow them exactly. "
    "Player characters are identified by their pinned KB objects (id prefix 'pc.'). "
    "Write from GM voice only: describe what the world does, what NPCs say and do, "
    "what the environment presents. "
    "Never write PC decisions, thoughts, feelings, or roll any dice. "
    "Stop at every decision point and yield to the player."
)

REQUIRED_PINS: frozenset[str] = frozenset({"rules.dnd", "rules.engagement"})

INSTRUCTION_CONTINUE = "Continue the scene, then pause for player response."

INSTRUCTION_WITH_PROMPT = (
    "Continue the scene following these instructions: {prompt}. "
    "Then yield to the user to allow their player(s) to act when appropriate."
)


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class PlayOperator(Operator):
    name: ClassVar[str] = "play"
    requires_id: ClassVar[bool] = False
    limited_to_datasets: ClassVar[list[str]] = ['dnd']
    use_command_tools: ClassVar[bool] = False  # speed over knowledge; @mention covers lookups

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
        """Require ``rules.dnd``, ``rules.engagement``, and at least one ``pc.*`` pin.

        Checks explicit *pins* plus any ``kb_pin`` entries in the cursor's
        front matter.
        """
        fm_raw = cursor.front_matter().get("kb_pin", [])
        fm_pins: list[str] = (
            [p for p in fm_raw if isinstance(p, str)]  # pyright: ignore[reportUnknownVariableType]
            if isinstance(fm_raw, list) else []
        )
        all_pins = fm_pins + pins
        bases = {p.rstrip("+") for p in all_pins}

        missing = REQUIRED_PINS - bases
        if missing:
            raise OperatorError(
                "play requires the following KB objects to be pinned: "
                + ", ".join(sorted(missing))
                + " — add them with --pin or kb_pin front matter"
            )

        if not any(b.startswith("pc.") for b in bases):
            raise OperatorError(
                "play requires at least one player character (pc.*) to be pinned — "
                "add a pc.* KB object with --pin or kb_pin front matter"
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
        prompt_snippet=(
            "Use the 'play' tool when the narrative reaches a moment that requires player "
            "agency — a decision point, an encounter, or a challenge where the player "
            "characters must act or respond. The play operator narrates in GM voice and "
            "stops for player input. Provide 'prompt' to describe the situation they face."
        ),
        keep_text=True,
    )
)
