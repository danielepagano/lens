"""Play operator: GM-voice narrative that preserves player agency.

``lens play [PROMPT]`` generates narrative in the voice of a Game Master —
describing what player characters observe, hear, and encounter — without
writing what they think, feel, decide, or do.  The operator stops at decision
or action points, giving the player space to respond.

Session lifecycle
-----------------
*  First call → creates a sub-node (``play[-module][-prompt-slug]``), auto-pins
   ``rules.system`` and ``rules.rpg``, and runs the first inline generation
   inside it.
*  Subsequent calls inside the same session → append new inline blocks.
   Front matter is updated when ``--module`` changes or new pins/unpins are
   supplied.
*  ``--end`` → appends close tag ``[/play:<id>]: #`` to the parent.

Module handling
---------------
``--module <key>`` pins ``rules.<key>`` in the sub-node front matter (e.g.
``rules.combat``, ``rules.downtime``).  Only one *extra* module is active at a
time; switching ``--module`` removes all ``rules.*`` pins except the auto-pinned
``rules.system`` and ``rules.rpg``.

Requires at least one ``pc.*`` KB object pinned (at any ancestor level) so the
LLM knows who the player characters are.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from lens.core.context import CrawlResult
from lens.core.operator import OperatorError
from lens.core.operators.session import SessionOperator
from lens.core.project import ProjectSession
from lens.core.narrative import NarrativeNode
from lens.core.storage import Storage
from lens.core.tools import OperatorToolDef


def _pc_marker(params: dict[str, Any]) -> str:
    key = params.get("pc_key")
    if not key:
        raise OperatorError(
            "play could not resolve PC key (no pinned pc.* in context)"
        )
    segments = key.replace("_", "-").split("-")
    return " ".join(s.capitalize() for s in segments if s)

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the Game Master. "
    "The Rules of Engagement are pinned in your context — follow them exactly. "
    "Player characters are identified by their pinned KB objects (id prefix 'pc.'). "
    "Write from GM voice only: describe what the world does, what NPCs say and do, "
    "what the environment presents. If you see KB['encounter.<name>'] object, "
    "it is a script for the current situation, and you must follow it with the highest priority. "
    "Never write PC decisions, thoughts, feelings, or roll any dice. "
    "Stop at every decision point and yield to the player."
)

REQUIRED_PINS: frozenset[str] = frozenset({"rules.system", "rules.rpg"})

def _instruction_with_prompt(prompt: str, pc_marker: str) -> str:
    return (
        "Continue the scene based on what the PC says below. Follow the script of any KB encounter given. "
        "Follow the decision gates: adjuticate, narratte, resolve, and engage.\n"
        f"> [{pc_marker}] {prompt}\n\n"
    )


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class PlayOperator(SessionOperator):
    name: ClassVar[str] = "play"
    requires_id: ClassVar[bool] = True
    limited_to_datasets: ClassVar[list[str]] = ["rpg"]
    excluded_operator_tools: ClassVar[frozenset[str]] = frozenset({"write"})

    module_prefix: ClassVar[str] = "rules."
    auto_pins: ClassVar[list[str]] = ["rules.system", "rules.rpg"]
    summarize_on_end: ClassVar[bool] = True

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
        return f"> [{_pc_marker(params)}] {prompt}\n\n"

    @classmethod
    def check_requirements(cls, crawl_result: CrawlResult) -> None:
        """Require ``rules.system``, ``rules.rpg``, and at least one ``pc.*`` pin.

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

    # ------------------------------------------------------------------
    # SessionOperator hooks — delegate to run_inline with cursor override
    # ------------------------------------------------------------------

    @classmethod
    async def _run_fresh(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        node: NarrativeNode,
        setup_storage: Storage,
        prompt: str | None,
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        **kwargs: Any,
    ) -> None:
        extra_params = kwargs.get("extra_params")
        on_confirm = kwargs.get("on_confirm")
        await cls.run_inline(
            session=session,
            narrative=narrative,
            prompt=prompt,
            pins=[],
            unpins=[],
            llm_id=llm_id,
            retry=False,
            on_token=on_token,
            _cursor_override=node,
            extra_params=extra_params,
            cancel_event=cancel_event,
            on_confirm=on_confirm,
        )

    @classmethod
    async def _run_inside(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        node: NarrativeNode,
        prompt: str | None,
        module_id: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        retry: bool,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        **kwargs: Any,
    ) -> None:
        extra_params = kwargs.get("extra_params")
        on_confirm = kwargs.get("on_confirm")

        if retry:
            # For retry: update front-matter with the same owner as the
            # pending annotation so pending owner stays consistent.
            if module_id or pins or unpins:
                probe_storage = session.new_storage()
                probe_op = cls(probe_storage, narrative)
                existing_ann = probe_op.find_open_annotation(node)
                if existing_ann is not None:
                    rel_path = str(node.md_path().relative_to(session.git_root))
                    ann_owner = cls._owner_for_ann(existing_ann, rel_path)
                    fm_storage = session.new_storage(owner=ann_owner)
                else:
                    fm_storage = session.new_storage()
                cls._update_front_matter_for_call(
                    node, module_id, pins, unpins, fm_storage, session
                )
        else:
            # Non-retry: stage pending, update front-matter, stage again.
            probe_storage = session.new_storage()
            if probe_storage.has_pending():
                probe_storage.stage_all()

            if module_id or pins or unpins:
                fm_storage = session.new_storage()
                cls._update_front_matter_for_call(
                    node, module_id, pins, unpins, fm_storage, session
                )
                fm_storage.stage_all()

        # Delegate to run_inline with cursor override — it handles
        # fresh/continue/retry logic for the inline annotation.
        await cls.run_inline(
            session=session,
            narrative=narrative,
            prompt=prompt,
            pins=[],
            unpins=[],
            llm_id=llm_id,
            retry=retry,
            on_token=on_token,
            _cursor_override=node,
            extra_params=extra_params,
            cancel_event=cancel_event,
            on_confirm=on_confirm,
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
