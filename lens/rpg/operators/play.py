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
*  ``--wait`` → append only the player line (and optional HTML comment with
   expanded ``@mentions``) to the session node; no LLM call. Use for multiple
   player actions before the GM responds.

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

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from lens.core.context import CrawlResult, crawl
from lens.core.dice import DiceError, substitute_rolls
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
    "The user may @-mention items in their text, like 'I cast @spell.hex' or 'I use @feature.aasimar-celestial-revelation', "
    "in these cases the system will also provide the KB item content for the mentioned item for your reference; "
    "use the attached item to understand what the user did and appropriate incorporate it the fiction; "
    "you do no have to repeat the content (the user already knows), you have to integrate it seamlessly without mentioning the rules, "
    "for example if an effect heals a user, say how the healing manifest; if they cast a spell, say what it looks like as they do, "
    "and what the results in the fiction are. User will not always do this, only when they want you to incorportate features in fiction. "
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
    # --wait: append player line (+ optional KB HTML comment) without LLM
    # ------------------------------------------------------------------

    @classmethod
    async def _run_wait_only(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str,
        pins: list[str],
        unpins: list[str],
        extra_params: dict[str, Any] | None,
        _cursor_override: NarrativeNode | None,
    ) -> None:
        cursor = (
            _cursor_override
            if _cursor_override is not None
            else narrative.find_cursor()
        )
        if not cursor.key_path:
            raise OperatorError("play --wait requires a cursor inside a play session sub-node")

        crawl_result = crawl(cursor, extra_pins=pins, extra_unpins=unpins)
        cls.check_requirements(crawl_result)
        params: dict[str, Any] = {"prompt": prompt}
        if extra_params:
            params.update(extra_params)
        cls.enrich_params(crawl_result, params)
        marker = _pc_marker(params)

        block = f"> [{marker}] {prompt}\n"
        mention_ids = cls.mention_pins(prompt, session.project_root)
        if mention_ids:
            objs = session.kb.get_objects(mention_ids)
            parts: list[str] = []
            for mid in mention_ids:
                obj = objs.get(mid)
                if obj is not None:
                    parts.append(obj.format(strip_html_comments=True))
            if parts:
                block += "\n<!---\n" + "".join(parts) + "-->\n"

        session_id = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=cursor.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        parent_rel = str(parent.md_path().relative_to(session.git_root))
        owner = cls.owner_id(session_id, parent_rel)
        storage = session.new_storage(owner=owner)
        md = cursor.md_path()
        current = md.read_text(encoding="utf-8")
        if current.strip():
            sep = "\n" if current.endswith("\n") else "\n\n"
        else:
            sep = ""
        storage.write_file(md, current + sep + block)

    @classmethod
    async def run_inline(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        retry: bool,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        _tool_call_depth: int = 0,
        on_confirm: Callable[[str, str], Awaitable[bool]] | None = None,
        _chain_storage: Storage | None = None,
        _cursor_override: NarrativeNode | None = None,
        extra_params: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        ep = dict(extra_params or {})
        if ep.pop("wait", False):
            if retry:
                raise OperatorError("play --wait cannot be combined with --retry")
            if not prompt:
                raise OperatorError("play --wait requires a prompt")
            try:
                resolved = substitute_rolls(prompt)
            except DiceError as e:
                raise OperatorError(str(e)) from e
            await cls._run_wait_only(
                session=session,
                narrative=narrative,
                prompt=resolved,
                pins=list(pins),
                unpins=list(unpins),
                extra_params=ep if ep else None,
                _cursor_override=_cursor_override,
            )
            return
        await super().run_inline(
            session=session,
            narrative=narrative,
            prompt=prompt,
            pins=pins,
            unpins=unpins,
            llm_id=llm_id,
            retry=retry,
            on_token=on_token,
            _tool_call_depth=_tool_call_depth,
            on_confirm=on_confirm,
            _chain_storage=_chain_storage,
            _cursor_override=_cursor_override,
            extra_params=ep if ep else None,
            cancel_event=cancel_event,
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
