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

from lens.core.context import CrawlResult
from lens.core.operator import Operator, OperatorError
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

INSTRUCTION_WITH_PROMPT = (
    "> [PLAYER] {prompt}\n\n---\n\n"
    "Continue the scene following the player's input above. "
    "Then yield to the user so the player(s) can act when appropriate. "
    "HARD RULE: DO NOT DECIDE OR ACT FOR THE PC CHARACTER."
)


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class PlayOperator(Operator):
    name: ClassVar[str] = "play"
    requires_id: ClassVar[bool] = False
    limited_to_datasets: ClassVar[list[str]] = ['dnd']
    excluded_operator_tools: ClassVar[frozenset[str]] = frozenset({"write"})

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt")
        if not prompt:
            raise OperatorError("play requires a prompt (e.g. what the player says or does)")
        return INSTRUCTION_WITH_PROMPT.format(prompt=prompt)

    def content_prefix_for_fresh(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt") or ""
        return f"> [PLAYER] {prompt}\n\n---\n\n"

    @classmethod
    def check_requirements(cls, crawl_result: CrawlResult) -> None:
        """Require ``rules.dnd``, ``rules.engagement``, and at least one ``pc.*`` pin.

        Uses ``crawl_result.pinned_ids`` — the canonical effective pin list
        after the full ancestor walk — so pins at any level in the hierarchy
        (including ancestor nodes and operator annotations) are seen correctly.
        """
        pinned = set(crawl_result.pinned_ids)
        missing = REQUIRED_PINS - pinned
        if missing:
            raise OperatorError(
                "play requires the following KB objects to be pinned: "
                + ", ".join(sorted(missing))
                + " — add them with --pin or kb_pin front matter"
            )

        if not any(pid.startswith("pc.") for pid in crawl_result.pinned_ids):
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
            "required": ["prompt"],
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
