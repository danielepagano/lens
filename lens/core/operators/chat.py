"""Chat operator: character-to-character conversation.

``lens chat --as <kb.id> [PROMPT]`` has the AI speak as a specific character
in response to the current scene context.  The optional prompt provides stage
directions (``--with`` mode) or is the opening beat of the exchange.

``lens chat --as npc.bob --with pc.amy [STAGE DIRECTIONS]`` opens a ``chat``
session sub-node for a two-character conversation.  Inside the session,
``lens chat [TEXT]`` appends TEXT attributed to the ``--with`` character and
the AI responds as ``--as``.  A new interlocutor can be introduced mid-session
with a different ``--as`` value.

Session lifecycle
-----------------
* First call → creates a sub-node (``chat[-prompt-slug]``), pins the ``--as``
  and ``--with`` character KB objects, and runs the first AI response.
* Subsequent calls inside the session → appends the user's ``--with`` character
  line, then AI responds as the ``--as`` character (falling back to the last
  annotation's stored ``as_kb_id`` when ``--as`` is omitted).
* ``--end`` → closes the session with a short prose summary.

Character attribution
---------------------
Character lines use blockquote format: ``> [CharacterName] what they say``.
Action beats: ``> [CharacterName] *she set down the cup*``.
Names are derived from the KB key suffix (e.g. ``npc.bob-the-smith`` → ``Bob The Smith``).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, cast

from lens.core.annotations import parse_annotations
from lens.core.context import CrawlResult
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.session import SessionOperator, prompt_to_slug
from lens.core.prompts import PromptStore
from lens.core.project import ProjectSession
from lens.core.storage import Storage

_NONSLUG_RE = re.compile(r"[^a-z0-9-]+")


def _titlecase_kb_key(kb_id: str) -> str:
    """Convert a KB id (e.g. ``npc.bob-the-smith``) to a display name (``Bob The Smith``)."""
    key = kb_id.split(".", 1)[-1] if "." in kb_id else kb_id
    segments = key.replace("_", "-").split("-")
    return " ".join(s.capitalize() for s in segments if s)


class ChatOperator(SessionOperator):
    """Character-to-character conversation operator."""

    name: ClassVar[str] = "chat"
    requires_id: ClassVar[bool] = True
    summarize_on_end: ClassVar[bool] = True

    # ── Prompt interface ───────────────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("chat.system")

    def build_instruction(self, params: dict[str, Any]) -> str:
        as_kb_id: str = params.get("as_kb_id") or ""
        as_name = _titlecase_kb_key(as_kb_id) if as_kb_id else "the character"
        directions: str | None = params.get("prompt") or None
        prompts = PromptStore(self.project_root)
        if directions:
            return prompts.format(
                "chat.instruction_with_directions",
                as_name=as_name,
                directions=directions,
            )
        return prompts.format("chat.instruction_continue", as_name=as_name)

    @classmethod
    def enrich_params(cls, crawl_result: CrawlResult, params: dict[str, Any]) -> None:
        """Validate that the ``--as`` character is in the effective pin list."""
        as_kb_id = params.get("as_kb_id")
        if not as_kb_id:
            raise OperatorError(
                "chat requires --as <kb.id> to specify the character the AI will voice"
            )
        if as_kb_id not in crawl_result.pinned_ids:
            raise OperatorError(
                f"--as '{as_kb_id}' must be pinned — "
                "it is auto-pinned when starting a new session; "
                "use --pin to add it when continuing"
            )

    # ── Session param helpers ──────────────────────────────────────────────

    @classmethod
    def _derive_session_params(cls, node: NarrativeNode) -> dict[str, str]:
        """Read ``as_kb_id`` and ``with_kb_id`` from the last chat annotation in *node*."""
        text = node.md_path().read_text(encoding="utf-8")
        anns = [a for a in parse_annotations(text) if a.operator == cls.name]
        for ann in reversed(anns):
            result: dict[str, str] = {}
            if "as_kb_id" in ann.params:
                result["as_kb_id"] = str(ann.params["as_kb_id"])
            val = ann.params.get("with_kb_id")
            if val:
                result["with_kb_id"] = str(val)
            if result:
                return result
        return {}

    @classmethod
    def _extract_extra(cls, kwargs: dict[str, Any]) -> tuple[str | None, str | None]:
        """Pull ``as_kb_id`` and ``with_kb_id`` from ``extra_params`` in *kwargs*."""
        raw = kwargs.get("extra_params")
        ep: dict[str, Any] = {}
        if isinstance(raw, dict):
            raw_map = cast(dict[object, object], raw)
            for k, v in raw_map.items():
                if isinstance(k, str):
                    ep[k] = v
        as_kb_id = ep.get("as_kb_id") if isinstance(ep.get("as_kb_id"), str) else None
        with_kb_id = ep.get("with_kb_id") if isinstance(ep.get("with_kb_id"), str) else None
        return as_kb_id, with_kb_id

    # ── User-character line helper ─────────────────────────────────────────

    @classmethod
    def _with_display_name(cls, with_kb_id: str | None) -> str:
        return _titlecase_kb_key(with_kb_id) if with_kb_id else "User"

    @classmethod
    async def _append_with_line(
        cls,
        *,
        session: ProjectSession,
        node: NarrativeNode,
        prompt: str,
        with_kb_id: str | None,
    ) -> None:
        """Append the user's character blockquote to the session *node*.

        The storage owner is keyed to the parent's session annotation so that
        the subsequent ``run_inline`` call sees it as "not my owner" and stages
        it automatically before generating the AI response.
        """
        marker = cls._with_display_name(with_kb_id)
        block = f"> [{marker}] {prompt}\n"
        md = node.md_path()
        current = md.read_text(encoding="utf-8")
        sep = "\n" if current.strip() and current.endswith("\n") else (
            "\n\n" if current.strip() else ""
        )
        if node.key_path:
            session_id = node.key_path[-1]
            parent = NarrativeNode(
                narrative_root=node.narrative_root,
                key_path=node.key_path[:-1],
            )
            parent_rel = str(parent.md_path().relative_to(session.git_root))
            owner = cls.owner_id(session_id, parent_rel)
            storage = session.new_storage(owner=owner)
        else:
            storage = session.new_storage()
        storage.write_file(md, current + sep + block)

    # ── Session ID generation ──────────────────────────────────────────────

    @classmethod
    def _make_chat_slug(
        cls,
        as_kb_id: str | None,
        with_kb_id: str | None,
        prompt: str | None,
        cursor: NarrativeNode,
    ) -> str:
        """Build a session slug from character keys and optional stage directions.

        Pattern: ``chat-<as-key>[-<with-key>][-<direction-words>][-N]``

        Examples:
        - ``--as npc.bob --with pc.amy "awkward banter"`` → ``chat-bob-amy-awkward-banter``
        - ``--as npc.bob`` → ``chat-bob``
        - Conflict on ``chat-bob`` → ``chat-bob-1``
        """
        parts: list[str] = []
        if as_kb_id:
            key = as_kb_id.split(".", 1)[-1] if "." in as_kb_id else as_kb_id
            parts.append(_NONSLUG_RE.sub("-", key.lower()).strip("-"))
        if with_kb_id:
            key = with_kb_id.split(".", 1)[-1] if "." in with_kb_id else with_kb_id
            parts.append(_NONSLUG_RE.sub("-", key.lower()).strip("-"))
        if prompt:
            direction_slug = prompt_to_slug(prompt, max_words=3)
            if direction_slug:
                parts.append(direction_slug)

        base = cls.name + ("-" + "-".join(parts) if parts else "")
        existing = set(cursor.child_keys())
        if base not in existing:
            return base
        n = 1
        while f"{base}-{n}" in existing:
            n += 1
        return f"{base}-{n}"

    @classmethod
    async def run_session(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str | None = None,
        module_id: str | None = None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None = None,
        reasoning: str | None = None,
        retry: bool = False,
        end: bool = False,
        slug: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_stream_target: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        """Override to inject a character-keyed slug for new sessions."""
        if not end and not retry and slug is None:
            session_node, _ = cls.find_active_session(narrative)
            if session_node is None:
                raw = kwargs.get("extra_params")
                ep: dict[str, Any] = {}
                if isinstance(raw, dict):
                    raw_map = cast(dict[object, object], raw)
                    for k, v in raw_map.items():
                        if isinstance(k, str):
                            ep[k] = v
                as_kb_id = ep.get("as_kb_id") if isinstance(ep.get("as_kb_id"), str) else None
                with_kb_id = ep.get("with_kb_id") if isinstance(ep.get("with_kb_id"), str) else None
                cursor = narrative.find_cursor()
                slug = cls._make_chat_slug(as_kb_id, with_kb_id, prompt, cursor)
        return await super().run_session(
            session=session,
            narrative=narrative,
            prompt=prompt,
            module_id=module_id,
            pins=pins,
            unpins=unpins,
            llm_id=llm_id,
            reasoning=reasoning,
            retry=retry,
            end=end,
            slug=slug,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=cancel_event,
            **kwargs,
        )

    # ── SessionOperator hooks ──────────────────────────────────────────────

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
        reasoning: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        **kwargs: Any,
    ) -> None:
        as_kb_id, with_kb_id = cls._extract_extra(kwargs)
        if not as_kb_id:
            raise OperatorError("--as is required when starting a chat session")

        # Prompt here carries optional stage directions; stored in annotation
        # params so build_instruction can include them in the first AI turn.
        await cls.run_inline(
            session=session,
            narrative=narrative,
            prompt=prompt,
            pins=[],
            unpins=[],
            llm_id=llm_id,
            reasoning=reasoning,
            retry=False,
            on_token=on_token,
            _cursor_override=node,
            extra_params={"as_kb_id": as_kb_id, "with_kb_id": with_kb_id},
            cancel_event=cancel_event,
            empty_prompt_ok=True,
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
        reasoning: str | None,
        retry: bool,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        **kwargs: Any,
    ) -> None:
        as_kb_id, with_kb_id = cls._extract_extra(kwargs)

        # Fall back to the last annotation's stored params when not re-specified.
        derived = cls._derive_session_params(node)
        if not as_kb_id:
            as_kb_id = derived.get("as_kb_id")
        if not with_kb_id:
            with_kb_id = derived.get("with_kb_id")

        if not as_kb_id:
            raise OperatorError(
                "no character found in session — specify --as <kb.id> to identify "
                "who the AI voices"
            )

        if retry:
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
            await cls.run_inline(
                session=session,
                narrative=narrative,
                prompt=prompt,  # forwarded as feedback to _do_retry
                pins=[],
                unpins=[],
                llm_id=llm_id,
                reasoning=reasoning,
                retry=True,
                on_token=on_token,
                _cursor_override=node,
                extra_params={"as_kb_id": as_kb_id, "with_kb_id": with_kb_id},
                cancel_event=cancel_event,
                empty_prompt_ok=True,
            )
            return

        # Non-retry: stage pending, apply front-matter changes, append user line.
        probe_storage = session.new_storage()
        if probe_storage.has_pending():
            probe_storage.stage_all()

        if module_id or pins or unpins:
            fm_storage = session.new_storage()
            cls._update_front_matter_for_call(
                node, module_id, pins, unpins, fm_storage, session
            )
            fm_storage.stage_all()

        if prompt:
            await cls._append_with_line(
                session=session,
                node=node,
                prompt=prompt,
                with_kb_id=with_kb_id,
            )

        # AI responds as the --as character; user text is already in the passage.
        await cls.run_inline(
            session=session,
            narrative=narrative,
            prompt=None,
            pins=[],
            unpins=[],
            llm_id=llm_id,
            reasoning=reasoning,
            retry=False,
            on_token=on_token,
            _cursor_override=node,
            extra_params={"as_kb_id": as_kb_id, "with_kb_id": with_kb_id},
            cancel_event=cancel_event,
            empty_prompt_ok=True,
        )
