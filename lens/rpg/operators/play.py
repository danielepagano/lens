"""Play operator: GM-voice narrative that preserves player agency.

``lens play [PROMPT]`` generates narrative in the voice of a Game Master —
describing what player characters observe, hear, and encounter — without
writing what they think, feel, decide, or do.  The operator stops at decision
or action points, giving the player space to respond.

Requires ``rules.system`` and ``rules.engagement`` to be pinned (mechanics layer
and player-AI contract), plus at least one ``pc.*`` KB object
so the LLM knows who the player characters are.
"""

from __future__ import annotations

from typing import Any, ClassVar

from lens.core.context import CrawlResult
from lens.core.operator import Operator, OperatorError
from lens.core.tools import OperatorToolDef


def _pc_marker(params: dict[str, Any]) -> str:
    key = params.get("pc_key")
    if not key:
        raise OperatorError(
            "play could not resolve PC key (no pinned pc.* in context)"
        )
    return key.upper()

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the Game Master. "\
    "The Rules of Engagement are pinned in your context — follow them exactly. "\
    "Player characters are identified by their pinned KB objects (id prefix 'pc.'). "\
    "Write from GM voice only: describe what the world does, what NPCs say and do, "\
    "what the environment presents. If you see KB['encounter.<name>'] object, "\
    "it is a script for the current situation, and you must follow it with the highest priority. "\
    "Never write PC decisions, thoughts, feelings, or roll any dice. "\
    "Stop at every decision point and yield to the player."
)

REQUIRED_PINS: frozenset[str] = frozenset({"rules.system", "rules.engagement"})

def _instruction_with_prompt(prompt: str, pc_marker: str) -> str:
    return (        
        "Continue the scene based on what the PC says below. Follow the script of any KB encounter given. "\
        "Follow the decision gates: adjuticate, narratte, resolve, and engage.\n"
        f"> [{pc_marker}] {prompt}\n\n---\n\n"
    )


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class PlayOperator(Operator):
    name: ClassVar[str] = "play"
    requires_id: ClassVar[bool] = False
    limited_to_datasets: ClassVar[list[str]] = ["rpg"]
    excluded_operator_tools: ClassVar[frozenset[str]] = frozenset({"write"})

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    @classmethod
    def enrich_params(cls, crawl_result: CrawlResult, params: dict[str, Any]) -> None:
        pinned_pcs = [p for p in crawl_result.pinned_ids if p.startswith("pc.")]
        as_pc = params.pop("as_pc", None)
        if as_pc is not None:
            pc_id = f"pc.{as_pc}" if not as_pc.startswith("pc.") else as_pc
            if pc_id not in pinned_pcs:
                raise OperatorError(
                    f"-as {as_pc!r} is not a pinned PC (pinned pc.*: "
                    + ", ".join(sorted(pinned_pcs))
                    + ")"
                )
            params["pc_key"] = pc_id.split(".", 1)[1]
            return
        for pid in crawl_result.pinned_ids:
            if pid.startswith("pc."):
                params["pc_key"] = pid.split(".", 1)[1]
                return

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt")
        if not prompt:
            raise OperatorError("play requires a prompt (e.g. what the player says or does)")
        return _instruction_with_prompt(prompt, _pc_marker(params))

    def content_prefix_for_fresh(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt") or ""
        return f"> [{_pc_marker(params)}] {prompt}\n\n---\n\n"

    @classmethod
    def check_requirements(cls, crawl_result: CrawlResult) -> None:
        """Require ``rules.system``, ``rules.engagement``, and at least one ``pc.*`` pin.

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
