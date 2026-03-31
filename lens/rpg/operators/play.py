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
*  Default → append only the player/character line (and optional HTML comment
   with expanded ``@mentions``) to the session node; no LLM call.
*  ``--pass`` → call the GM / LLM to respond, writing output inside a
   ``[play]: # ... [/play]: #`` block.

Module handling
---------------
``--module <key>`` pins ``rules.<key>`` in the sub-node front matter (e.g.
``rules.combat``, ``rules.downtime``).  Only one *extra* module is active at a
time; switching ``--module`` removes all ``rules.*`` pins except the auto-pinned
``rules.system`` and ``rules.rpg``.

Requires at least one ``pc.*`` KB object pinned (at any ancestor level) so the
LLM knows who the player characters are.

Refuses to run if any ``design.*`` KB object is pinned in context — design
modules belong in ``lens design`` sessions, not mixed into play prompts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, cast

from lens.core.context import CrawlResult, crawl
from lens.core.dice import DiceError, substitute_rolls
from lens.core.operator import OperatorError
from lens.core.operators.session import SessionOperator
from lens.core.prompts import PromptStore
from lens.core.project import ProjectSession
from lens.core.narrative import NarrativeNode
from lens.core.storage import Storage


def _titlecase_pc_key(key: str) -> str:
    segments = key.replace("_", "-").split("-")
    return " ".join(s.capitalize() for s in segments if s)

REQUIRED_PINS: frozenset[str] = frozenset({"rules.system", "rules.rpg"})

# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class PlayOperator(SessionOperator):
    name: ClassVar[str] = "play"
    requires_id: ClassVar[bool] = True
    limited_to_datasets: ClassVar[list[str]] = ["rpg"]
    use_steps: ClassVar[bool] = False

    module_prefix: ClassVar[str] = "rules."
    auto_pins: ClassVar[list[str]] = ["rules.system", "rules.rpg"]
    summarize_on_end: ClassVar[bool] = True

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("play.system")

    @classmethod
    def enrich_params(cls, crawl_result: CrawlResult, params: dict[str, Any]) -> None:
        # Play annotations intentionally store no metadata. We only validate
        # `--as` against pinned PCs when used.
        pinned_pcs = [p for p in crawl_result.pinned_ids if p.startswith("pc.")]
        as_pc = params.pop("as_pc", None)
        if as_pc is None:
            return
        pc_id = f"pc.{as_pc}" if not as_pc.startswith("pc.") else as_pc
        if pc_id not in pinned_pcs:
            raise OperatorError(
                f"-as {as_pc!r} is not a pinned PC (pinned pc.*: "
                + ", ".join(sorted(pinned_pcs))
                + ")"
            )

    def build_instruction(self, params: dict[str, Any]) -> str:
        # The GM responds based on the current passage, which includes any
        # newly appended player/character line(s).
        return PromptStore(self.project_root).get("play.instruction_continue")

    def content_prefix_for_fresh(self, params: dict[str, Any]) -> str:
        # Player/character lines are persisted outside the annotation block.
        return ""

    # ------------------------------------------------------------------
    # Player/character line persistence (+ KB @mention expansion)
    # ------------------------------------------------------------------

    @classmethod
    def _speaker_marker(cls, crawl_result: CrawlResult, as_pc: str | None) -> str:
        if as_pc is None:
            return "Player"
        pinned_pcs = [p for p in crawl_result.pinned_ids if p.startswith("pc.")]
        pc_id = f"pc.{as_pc}" if not as_pc.startswith("pc.") else as_pc
        if pc_id not in pinned_pcs:
            raise OperatorError(
                f"-as {as_pc!r} is not a pinned PC (pinned pc.*: "
                + ", ".join(sorted(pinned_pcs))
                + ")"
            )
        key = pc_id.split(".", 1)[1]
        return _titlecase_pc_key(key)

    @classmethod
    def _kb_already_in_node(cls, node_text: str, kb_id: str) -> bool:
        return f"KB['{kb_id}']" in node_text

    @classmethod
    async def _append_player_line(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str,
        pins: list[str],
        unpins: list[str],
        as_pc: str | None,
        _cursor_override: NarrativeNode | None,
    ) -> None:
        cursor = _cursor_override if _cursor_override is not None else narrative.find_cursor()
        if not cursor.key_path:
            raise OperatorError("play requires a cursor inside a play session sub-node")

        crawl_result = crawl(cursor, extra_pins=pins, extra_unpins=unpins)
        cls.check_requirements(crawl_result)
        marker = cls._speaker_marker(crawl_result, as_pc)

        block = f"> [{marker}] {prompt}\n"

        mention_ids = cls.mention_pins(prompt, session.project_root)
        if mention_ids:
            objs = session.kb.get_objects(mention_ids)
            current_text = cursor.md_path().read_text(encoding="utf-8")
            parts: list[str] = []
            for mid in mention_ids:
                if cls._kb_already_in_node(current_text, mid):
                    continue
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
    def check_requirements(cls, crawl_result: CrawlResult) -> None:
        """Require ``rules.system``, ``rules.rpg``, and at least one ``pc.*`` pin.

        Uses ``crawl_result.pinned_ids`` — the canonical effective pin list
        after the full ancestor walk — so pins at any level in the hierarchy
        (including ancestor nodes and operator annotations) are seen correctly.
        """
        pinned = set(crawl_result.pinned_ids)
        design_pins = sorted(p for p in crawl_result.pinned_ids if p.startswith("design."))
        if design_pins:
            raise OperatorError(
                "play refuses to run while design modules are pinned ("
                + ", ".join(design_pins)
                + "). Design sessions use their own node; remove design.* from kb_pin "
                "here so prompts do not conflict with play."
            )
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
        _cursor_override: NarrativeNode | None = None,
        extra_params: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        await super().run_inline(
            session=session,
            narrative=narrative,
            prompt=None,
            pins=pins,
            unpins=unpins,
            llm_id=llm_id,
            retry=retry,
            on_token=on_token,
            _cursor_override=_cursor_override,
            extra_params=None,
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
        raw_extra = kwargs.get("extra_params")
        extra_params: dict[str, Any] = {}
        if isinstance(raw_extra, dict):
            raw_map = cast(dict[object, object], raw_extra)
            for k_obj, v_obj in raw_map.items():
                if isinstance(k_obj, str):
                    extra_params[k_obj] = v_obj
        do_pass = bool(extra_params.get("pass", False))
        as_pc: str | None = (
            extra_params.get("as_pc") if isinstance(extra_params.get("as_pc"), str) else None
        )

        if prompt:
            try:
                resolved = substitute_rolls(prompt)
            except DiceError as e:
                raise OperatorError(str(e)) from e
            await cls._append_player_line(
                session=session,
                narrative=narrative,
                prompt=resolved,
                pins=[],
                unpins=[],
                as_pc=as_pc,
                _cursor_override=node,
            )

        if do_pass:
            await cls.run_inline(
                session=session,
                narrative=narrative,
                prompt=None,
                pins=[],
                unpins=[],
                llm_id=llm_id,
                retry=False,
                on_token=on_token,
                _cursor_override=node,
                extra_params=None,
                cancel_event=cancel_event,
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
        raw_extra = kwargs.get("extra_params")
        extra_params: dict[str, Any] = {}
        if isinstance(raw_extra, dict):
            raw_map = cast(dict[object, object], raw_extra)
            for k_obj, v_obj in raw_map.items():
                if isinstance(k_obj, str):
                    extra_params[k_obj] = v_obj
        do_pass = bool(extra_params.get("pass", False))
        as_pc: str | None = (
            extra_params.get("as_pc") if isinstance(extra_params.get("as_pc"), str) else None
        )

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

        if retry:
            await cls.run_inline(
                session=session,
                narrative=narrative,
                prompt=None,
                pins=[],
                unpins=[],
                llm_id=llm_id,
                retry=True,
                on_token=on_token,
                _cursor_override=node,
                extra_params=None,
                cancel_event=cancel_event,
            )
            return

        if prompt:
            try:
                resolved = substitute_rolls(prompt)
            except DiceError as e:
                raise OperatorError(str(e)) from e
            await cls._append_player_line(
                session=session,
                narrative=narrative,
                prompt=resolved,
                pins=[],
                unpins=[],
                as_pc=as_pc,
                _cursor_override=node,
            )

        if do_pass:
            await cls.run_inline(
                session=session,
                narrative=narrative,
                prompt=None,
                pins=[],
                unpins=[],
                llm_id=llm_id,
                retry=False,
                on_token=on_token,
                _cursor_override=node,
                extra_params=None,
                cancel_event=cancel_event,
            )


