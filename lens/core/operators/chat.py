"""Chat operator: character-to-character conversation.

``lens chat --as <kb.id> [PROMPT]`` has the AI speak as a specific character
in response to the current scene context.  The optional prompt provides stage
directions (``--with`` mode) or is the opening beat of the exchange.

``lens chat --as npc.bob --with pc.amy [STAGE DIRECTIONS]`` opens a ``chat``
session sub-node for a two-character conversation.  Inside the session,
``lens chat [TEXT]`` appends TEXT as the ``--with`` character (attributed dialogue
by default) and the AI responds as ``--as``, unless ``--wait`` skips the model.
A new interlocutor can be introduced mid-session with a different ``--as`` value.

Session lifecycle
-----------------
* First call → creates a sub-node (``chat[-prompt-slug]``), writes ``as_kb_id``
  / ``with_kb_id`` / ``prompt`` / optional ``kb_pin`` (user pins only) into the
  **parent** annotation so the whole setup + first AI turn is one atomic unstaged
  transaction.  A rollback removes the sub-node entirely and the user can retry.
* Subsequent calls inside the session → appends the user's ``--with`` character
  line (see session flags below), then unless ``--wait`` the AI responds as
  ``--as`` — in one unstaged transaction (rollback drops the new line and, when
  applicable, the reply together).  ``as_kb_id`` / ``with_kb_id`` are derived
  from the parent annotation and may be overridden per-call.
* ``--end`` → closes the session with a short prose summary.

Session flags (direct ``--with`` turns only)
--------------------------------------------
* ``--narrate`` — append the line as blockquote text only (``> …``), without the
  ``[CharacterName]`` prefix used for spoken dialogue.
* ``--wait`` — append the line(s) only; do not call the LLM and do not write a
  ``[chat]``…``[/chat]`` pair for that call.  Several user lines in a row stay one
  Markdown blockquote by inserting a line with only ``>`` between entries (so
  renderers do not collapse adjacent ``>`` lines into one paragraph).

Character attribution
---------------------
Character lines use blockquote format: ``> [CharacterName] what they say``.
Action beats: ``> [CharacterName] *she set the cup down*``.
With ``--narrate``, the same beat is written as ``> *she set the cup down*`` (no
name prefix).  Names are derived from the KB key suffix (e.g. ``npc.bob-the-smith`` → ``Bob The Smith``).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, ClassVar, cast

from lens.core.annotations import parse_annotations
from lens.core.context import CrawlResult, crawl
from lens.core.dice import DiceError
from lens.core.exceptions import ValidationError
from lens.core.knowledge import KnowledgeStore
from lens.core.generation_artifacts import GenerationArtifacts
from lens.core.llm import LLMError
from lens.core.llm_run import LlmRunRequest, run_llm
from lens.core.mentions import append_mention_annotations
from lens.core.narrative import NarrativeNode
from lens.core.exceptions import OperatorError
from lens.core.operators.session import SessionOperator, prompt_to_slug
from lens.core.pinning import pin as pin_node
from lens.core.prompts import PromptStore
from lens.core.project import ProjectSession, validate_slug
from lens.core.workflow_runner import WorkflowOutcome, WorkflowRunner


_NONSLUG_RE = re.compile(r"[^a-z0-9-]+")
_WITH_LINE_MODE_DIRECT = "direct"
_WITH_LINE_MODE_ASIDE = "aside"


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
    required_modalities: ClassVar[frozenset[str]] = frozenset({"attributed_dialogue"})

    # ── Prompt interface ───────────────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("chat.system")

    def build_instruction(self, params: dict[str, Any]) -> str:
        as_kb_id: str = params.get("as_kb_id") or ""
        with_kb_id: str | None = params.get("with_kb_id") or None
        as_name = _titlecase_kb_key(as_kb_id) if as_kb_id else "the character"
        directions: str | None = params.get("prompt") or None
        with_line_mode = params.get("with_line_mode")

        # Fetch the character's KB text and embed it directly in the task so
        # the AI knows exactly who it is embodying without searching.
        char_content = ""
        if as_kb_id:
            store = KnowledgeStore.for_project(self.project_root)
            objects = store.get_objects(ids=[as_kb_id])
            obj = objects.get(as_kb_id)
            if obj:
                char_content = obj.text.strip()

        prompts = PromptStore(self.project_root)
        with_name = _titlecase_kb_key(with_kb_id) if with_kb_id else "the counterpart"
        with_line = ""
        if with_kb_id and with_line_mode == _WITH_LINE_MODE_DIRECT:
            with_line = "\n" + prompts.format("chat.with_line_instruction", with_name=with_name)

        if directions:
            if with_line_mode == _WITH_LINE_MODE_ASIDE:
                return prompts.format(
                    "chat.instruction_with_aside_directions",
                    as_name=as_name,
                    char_content=char_content,
                    directions=directions,
                    with_name=with_name,
                )
            return prompts.format(
                "chat.instruction_with_directions",
                as_name=as_name,
                char_content=char_content,
                directions=directions,
                with_line=with_line,
                with_name=with_name,
            )
        return prompts.format(
            "chat.instruction_continue",
            as_name=as_name,
            char_content=char_content,
            with_line=with_line,
        )

    @classmethod
    def participants_for_crawl(cls, params: dict[str, Any]) -> dict[str, str]:
        """Map ``as_kb_id`` / ``with_kb_id`` to graph participants."""
        out: dict[str, str] = {}
        as_kb_id = params.get("as_kb_id")
        with_kb_id = params.get("with_kb_id")
        if isinstance(as_kb_id, str):
            out["as"] = as_kb_id
        if isinstance(with_kb_id, str):
            out["with"] = with_kb_id
        return out

    @staticmethod
    def _persist_opening_scene_markdown(prompt: str) -> str:
        p = prompt.strip()
        if not p:
            return ""
        if "\n" in p:
            return f"**Scene:**\n\n{p}\n\n"
        return f"> **Scene:** {p}\n\n"

    def content_prefix_for_fresh(self, params: dict[str, Any]) -> str:
        raw = params.get("prompt")
        if raw is None or not str(raw).strip():
            return ""
        return self._persist_opening_scene_markdown(str(raw))

    @classmethod
    def enrich_params(cls, crawl_result: CrawlResult, params: dict[str, Any]) -> None:
        """Validate that the ``--as`` character exists in the knowledge base."""
        as_kb_id = params.get("as_kb_id")
        if not as_kb_id:
            raise ValidationError(
                "chat requires --as <kb.id> to specify the character the AI will voice"
            )
        # Character sheets are pulled into crawl via session params (``--as`` /
        # ``--with``), not duplicated in ``kb_pin``, so we only validate existence
        # here.
        if crawl_result.project_root is not None:
            store = KnowledgeStore.for_project(crawl_result.project_root)
            if not store.exists(as_kb_id):
                raise ValidationError(
                    f"--as '{as_kb_id}' does not exist in the knowledge base"
                )

    # ── Session param helpers ──────────────────────────────────────────────

    @classmethod
    def _derive_session_params(cls, session_node: NarrativeNode) -> dict[str, Any]:
        """Read session fields from the parent's chat annotation.

        Includes ``as_kb_id`` and ``with_kb_id`` when set.
        """
        if not session_node.key_path:
            return {}
        session_id = session_node.key_path[-1]
        parent = NarrativeNode(
            narrative_root=session_node.narrative_root,
            key_path=session_node.key_path[:-1],
        )
        try:
            text = parent.md_path().read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        for ann in reversed(parse_annotations(text)):
            if (
                ann.operator == cls.name
                and ann.id == session_id
                and not ann.closing
                and not ann.self_closing
            ):
                result: dict[str, Any] = {}
                if "as_kb_id" in ann.params:
                    result["as_kb_id"] = str(ann.params["as_kb_id"])
                if "with_kb_id" in ann.params:
                    result["with_kb_id"] = str(ann.params["with_kb_id"])
                return result
        return {}

    @classmethod
    def _extract_extra(cls, kwargs: dict[str, Any]) -> tuple[str | None, str | None, bool, bool]:
        """Pull session flags and ``as_kb_id`` / ``with_kb_id`` from ``extra_params``."""
        raw = kwargs.get("extra_params")
        ep: dict[str, Any] = {}
        if isinstance(raw, dict):
            raw_map = cast(dict[object, object], raw)
            for k, v in raw_map.items():
                if isinstance(k, str):
                    ep[k] = v
        as_kb_id = ep.get("as_kb_id") if isinstance(ep.get("as_kb_id"), str) else None
        with_kb_id = ep.get("with_kb_id") if isinstance(ep.get("with_kb_id"), str) else None
        narrate = bool(ep.get("narrate"))
        wait = bool(ep.get("wait"))
        return as_kb_id, with_kb_id, narrate, wait

    @staticmethod
    def _sep_before_blockquote_user_line(original: str) -> str:
        """Newlines before appending the next user ``> …`` block.

        If the last non-empty line is already a blockquote, insert a **spacer**
        line that is only ``>`` (CommonMark: continues the quote; avoids renderers
        gluing ``> a`` + ``> b`` into one run-on line).  When the file already ends
        with ``\\n`` after the previous quote line, use ``>\\n`` — not ``\\n>\\n``,
        which would add an extra blank row.

        Otherwise return one or two newlines so the new block is not concatenated
        onto non-quote text on the same line.
        """
        if not original.strip():
            return ""
        last_nonempty = ""
        for line in original.rstrip("\n").split("\n")[::-1]:
            if line.strip():
                last_nonempty = line
                break
        if last_nonempty.lstrip().startswith(">"):
            return ">\n" if original.endswith("\n") else "\n>\n"
        if original.endswith("\n"):
            return "\n"
        return "\n\n"

    @classmethod
    def _format_direct_user_block(
        cls,
        *,
        with_kb_id: str | None,
        user_prompt: str,
        narrate: bool,
    ) -> str:
        raw = user_prompt.strip()
        if not raw:
            raise ValidationError("a non-empty prompt is required for this chat turn")
        lines_list = raw.splitlines()
        out: list[str] = []
        if narrate:
            for line in lines_list:
                out.append(">" if not line.strip() else f"> {line}")
            return "\n".join(out) + "\n"
        marker = cls._with_display_name(with_kb_id)
        first = True
        for line in lines_list:
            if first:
                out.append(f"> [{marker}] {line}")
                first = False
            else:
                out.append(f"> {line}")
        return "\n".join(out) + "\n"

    # ── User-character line helper ─────────────────────────────────────────

    @classmethod
    def _with_display_name(cls, with_kb_id: str | None) -> str:
        return _titlecase_kb_key(with_kb_id) if with_kb_id else "User"

    @classmethod
    async def _run_direct_with_turn(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        node: NarrativeNode,
        user_prompt: str,
        with_kb_id: str | None,
        as_kb_id: str,
        with_line_mode: str,
        narrate: bool,
        wait: bool,
        llm_id: str | None,
        reasoning: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        mentions: list[str] | None = None,
        includes: list[str] | None = None,
        workflow: WorkflowRunner | None = None,
    ) -> None:
        """Append the ``--with`` blockquote; optionally run the LLM and ``write_start``.

        With ``wait``, only the blockquote lines are appended (no ``[chat]`` pair),
        preserving one Markdown blockquote run across consecutive waits.

        Otherwise reuses a single :class:`~lens.core.storage.Storage` so the storage
        layer does not auto-stage the user line before ``write_start`` (which would
        split rollback semantics from ``run_inline``).
        """
        md = node.md_path()
        original = md.read_text(encoding="utf-8")
        try:
            user_prompt = cls.transform_storable_prompt(
                user_prompt, session=session, cursor=node
            )
        except DiceError as e:
            raise ValidationError(str(e)) from e
        block = cls._format_direct_user_block(
            with_kb_id=with_kb_id,
            user_prompt=user_prompt,
            narrate=narrate,
        )
        # The user's line is persisted as prose here, so scope it names is
        # recorded right under it and expands there — same shape as `play`.
        block = append_mention_annotations(
            block,
            cls.mention_params(
                user_prompt, mentions, includes, project_root=session.project_root
            ),
        )
        sep = cls._sep_before_blockquote_user_line(original)
        text_with_user = original + sep + block
        rel_path = str(md.relative_to(session.git_root))
        ann_line = cls.ann_line_for_append(text_with_user)
        owner = cls.owner_id(None, rel_path, line=ann_line)
        storage = session.new_storage(owner=owner)

        ann_params: dict[str, Any] = {
            "as_kb_id": as_kb_id,
            "with_kb_id": with_kb_id,
            "with_line_mode": with_line_mode,
        }
        pins: list[str] = []
        unpins: list[str] = []
        with_id = ann_params.get("with_kb_id")
        with_extra = (
            [str(with_id).strip()]
            if isinstance(with_id, str) and str(with_id).strip()
            else []
        )

        storage.write_file(md, text_with_user)

        if wait:
            return

        tag = ""
        artifacts = GenerationArtifacts()
        try:
            crawl_storage = session.new_storage()
            crawl_result = crawl(
                cls.crawl_spec(
                    node,
                    ann_params,
                    session=session,
                    narrative=narrative,
                    extra_pins=cls.merge_extra_pin_ids(list(pins), with_extra),
                    extra_unpins=unpins,
                    storage=crawl_storage,
                    participants=cls.participants_for_crawl(ann_params),
                )
            )
            cls.check_requirements(crawl_result)
            cls.enrich_params(crawl_result, ann_params)

            probe_op = cls(crawl_storage, narrative)
            tag = probe_op.build_open_tag(None, ann_params)
            ctx, resolved = probe_op._modality_context(
                crawl_result,
                ann_params,
                session=session,
                narrative=narrative,
            )
            messages = probe_op.build_messages(
                crawl_result,
                ann_params,
                session=session,
                narrative=narrative,
                resolved_modalities=resolved,
            )
            tools_payload, command_handlers = cls.merge_command_tools_for_generation(
                resolved, ctx, session.project_root, ann_params
            )

            artifacts = await run_llm(
                LlmRunRequest(
                    project_root=session.project_root,
                    messages=messages,
                    llm_id=llm_id,
                    tools=tools_payload,
                    command_tool_handlers=command_handlers,
                    resolved_modalities=resolved,
                    modality_context=ctx,
                    cancel_event=cancel_event,
                    on_token=on_token,
                    operator_name=cls.name,
                    reasoning=reasoning,
                ),
            )
        except LLMError as e:
            storage.write_file(md, original)
            raise OperatorError(f"LLM error: {e}") from e
        except Exception:
            storage.write_file(md, original)
            raise

        if artifacts.interrupted:
            storage.write_file(md, original)
            return

        if not artifacts.has_content():
            storage.write_file(md, original)
            raise OperatorError("no content generated")

        artifacts, _refine_warnings = await cls.apply_modality_post_refine(
            session,
            artifacts,
            resolved=resolved,
            ctx=ctx,
            workflow=workflow,
            on_token=on_token,
            cancel_event=cancel_event,
        )
        op = cls(storage, narrative)
        op.write_start(
            node,
            tag,
            artifacts=artifacts,
            verbatim_prefix=op.content_prefix_for_fresh(ann_params),
        )

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

    # ── Fresh session — atomic one-transaction setup ───────────────────────

    @classmethod
    async def _start_fresh_session(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        cursor: NarrativeNode,
        as_kb_id: str,
        with_kb_id: str | None,
        prompt: str | None,
        pins: list[str],
        llm_id: str | None,
        reasoning: str | None,
        slug: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        mentions: list[str] | None = None,
        includes: list[str] | None = None,
        workflow: WorkflowRunner | None = None,
    ) -> None:
        """Create child sub-node + generate first AI turn in one unstaged transaction.

        All session parameters (``as_kb_id``, ``with_kb_id``, ``prompt``,
        ``kb_pin``) are stored in the **parent** annotation so a rollback
        removes the whole session and the user can retry cleanly.
        """
        # Validate / compute slug.
        if slug is not None:
            if not validate_slug(slug):
                raise ValidationError(
                    f"invalid slug '{slug}' (alphanumeric, underscores, hyphens only)"
                )
            prefix = f"{cls.name}-"
            if not slug.startswith(prefix):
                slug = prefix + slug
            if slug in set(cursor.child_keys()):
                raise ValidationError(f"a node named '{slug}' already exists here")
            session_id = slug
        else:
            session_id = cls._make_chat_slug(as_kb_id, with_kb_id, prompt, cursor)

        rel_path = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(session_id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)

        # Resolve inline @ tokens in the scene context before storing.
        if prompt:
            try:
                prompt = cls.transform_storable_prompt(
                    prompt, session=session, cursor=cursor
                )
            except DiceError as e:
                raise ValidationError(str(e)) from e

        # Build parent annotation params — everything the session needs.
        ann_params: dict[str, Any] = {"as_kb_id": as_kb_id}
        if with_kb_id:
            ann_params["with_kb_id"] = with_kb_id
        if prompt:
            ann_params["prompt"] = prompt
        if pins:
            ann_params["kb_pin"] = list(pins)

        if reasoning:
            ann_params["reasoning"] = reasoning

        # Mentions from the opening beat seed the child, not the parent
        # annotation: the session's own node is where they have to expand, and
        # includes/mentions are never inherited across a node boundary.
        initial = append_mention_annotations(
            "",
            cls.mention_params(
                prompt, mentions, includes, project_root=session.project_root
            ),
        )

        # Create the child node; the parent annotation gets all the params.
        child_node = op.create_subnode(
            cursor, session_id, initial_content=initial or None, params=ann_params
        )

        # Pin KB objects into the child's front matter for crawl context.
        if pins:
            pin_node(child_node, pins, storage)

        if on_stream_target is not None:
            await on_stream_target(str(child_node.to_address()))

        # Validate character; build instruction params (prompt = stage directions).
        inst_params: dict[str, Any] = {
            "as_kb_id": as_kb_id,
            "with_kb_id": with_kb_id,
            "prompt": prompt,
            "with_line_mode": _WITH_LINE_MODE_DIRECT if with_kb_id else None,
        }

        # Crawl the child to assemble context (inherits ancestor pins).
        crawl_result = crawl(
            cls.crawl_spec(
                child_node,
                inst_params,
                session=session,
                narrative=narrative,
                extra_pins=cls.merge_extra_pin_ids(
                    list(pins),
                    [with_kb_id] if with_kb_id else [],
                ),
                storage=storage,
                participants=cls.participants_for_crawl(inst_params),
            )
        )
        cls.enrich_params(crawl_result, inst_params)

        # Generate the first AI turn using the same storage (no intermediate stage).
        probe_op = cls(storage, narrative)
        ctx, resolved = probe_op._modality_context(
            crawl_result,
            inst_params,
            session=session,
            narrative=narrative,
        )
        messages = probe_op.build_messages(
            crawl_result,
            inst_params,
            session=session,
            narrative=narrative,
            resolved_modalities=resolved,
        )
        tools_payload, command_handlers = cls.merge_command_tools_for_generation(
            resolved, ctx, session.project_root, inst_params
        )

        artifacts = GenerationArtifacts()
        try:
            artifacts = await run_llm(
                LlmRunRequest(
                    project_root=session.project_root,
                    messages=messages,
                    llm_id=llm_id,
                    tools=tools_payload,
                    command_tool_handlers=command_handlers,
                    resolved_modalities=resolved,
                    modality_context=ctx,
                    cancel_event=cancel_event,
                    on_token=on_token,
                    operator_name=cls.name,
                    reasoning=reasoning,
                ),
            )
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if artifacts.interrupted:
            return

        if not artifacts.has_content():
            raise OperatorError("no content generated")

        artifacts, _refine_warnings = await cls.apply_modality_post_refine(
            session,
            artifacts,
            resolved=resolved,
            ctx=ctx,
            workflow=workflow,
            on_token=on_token,
            cancel_event=cancel_event,
        )
        # Write the first AI turn — tag in child carries no redundant params.
        turn_tag = probe_op.build_open_tag(None, None)
        probe_op.write_start(
            child_node,
            turn_tag,
            artifacts=artifacts,
            verbatim_prefix=probe_op.content_prefix_for_fresh(inst_params),
        )
        # Everything (sub-node creation, parent annotation, first turn) is now
        # in one unstaged transaction.  Do NOT call storage.stage_all() here.

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
        reasoning: str | None = None,
        mentions: list[str] | None = None,
        includes: list[str] | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        extra_params: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
        on_status: Callable[[str], None] | None = None,
        on_info_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        _cursor_override: NarrativeNode | None = None,
        empty_prompt_ok: bool = False,
        workflow: WorkflowRunner | None = None,
    ) -> WorkflowOutcome | None:
        filtered: dict[str, Any] | None = None
        if extra_params:
            ep = dict(extra_params)
            ep.pop("narrate", None)
            ep.pop("wait", None)
            filtered = ep if ep else None
        return await super().run_inline(
            session=session,
            narrative=narrative,
            prompt=prompt,
            pins=pins,
            unpins=unpins,
            llm_id=llm_id,
            retry=retry,
            reasoning=reasoning,
            mentions=mentions,
            includes=includes,
            on_token=on_token,
            extra_params=filtered,
            cancel_event=cancel_event,
            on_status=on_status,
            on_info_event=on_info_event,
            _cursor_override=_cursor_override,
            empty_prompt_ok=empty_prompt_ok,
            workflow=workflow,
        )

    # ── run_session override ───────────────────────────────────────────────

    @classmethod
    async def run_session(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str | None = None,
        module_ids: Sequence[str] | None = None,
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
        on_status: Callable[[str], None] | None = None,
        on_info_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run a chat session (create, continue, or end).

        Fresh sessions are handled here atomically (one transaction).  Existing
        sessions and ``--end`` delegate to the base-class implementation.
        """
        if end:
            return await super().run_session(
                session=session,
                narrative=narrative,
                prompt=prompt,
                module_ids=module_ids,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                reasoning=reasoning,
                retry=retry,
                end=True,
                slug=slug,
                on_token=on_token,
                on_stream_target=on_stream_target,
                cancel_event=cancel_event,
                **kwargs,
            )

        session_node, _ = cls.find_active_session(narrative)

        if session_node is not None:
            # Continue inside an existing session — delegate to base class.
            return await super().run_session(
                session=session,
                narrative=narrative,
                prompt=prompt,
                module_ids=module_ids,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                reasoning=reasoning,
                retry=retry,
                end=False,
                slug=slug,
                on_token=on_token,
                on_stream_target=on_stream_target,
                cancel_event=cancel_event,
                on_status=on_status,
                on_info_event=on_info_event,
                **kwargs,
            )

        # Fresh session — atomic setup + first generation.
        as_kb_id, with_kb_id, _narrate, _wait = cls._extract_extra(kwargs)
        if not as_kb_id:
            raise ValidationError("--as is required when starting a chat session")

        cursor = narrative.find_cursor()
        fresh_mentions, fresh_includes = cls.session_mention_ids(kwargs)
        result = await cls._start_fresh_session(
            session=session,
            narrative=narrative,
            cursor=cursor,
            as_kb_id=as_kb_id,
            with_kb_id=with_kb_id,
            prompt=prompt,
            pins=list(pins),
            llm_id=llm_id,
            reasoning=reasoning,
            slug=slug,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=cancel_event,
            mentions=fresh_mentions,
            includes=fresh_includes,
            workflow=cast(WorkflowRunner | None, kwargs.get("workflow")),
        )
        await cls._run_post_inline_hooks(
            session=session,
            narrative=narrative,
            cursor=cursor,
            on_token=on_token,
            cancel_event=cancel_event,
            on_status=on_status,
            on_info_event=on_info_event,
        )
        return result

    # ── SessionOperator hooks ──────────────────────────────────────────────

    @classmethod
    async def _run_fresh(cls, **kwargs: Any) -> None:  # type: ignore[override]
        # Never called: run_session handles the fresh path directly.
        _ = kwargs
        raise ValidationError(
            "chat _run_fresh should not be called directly — use run_session"
        )  # pragma: no cover

    @classmethod
    async def _run_inside(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        node: NarrativeNode,
        prompt: str | None,
        module_ids: Sequence[str] | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        reasoning: str | None,
        retry: bool,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: Any | None,
        on_status: Callable[[str], None] | None = None,
        on_info_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> None:
        as_kb_id, with_kb_id, narrate, wait = cls._extract_extra(kwargs)

        # Fall back to the parent annotation's stored params when not re-specified.
        derived = cls._derive_session_params(node)
        session_as_kb_id = derived.get("as_kb_id")
        session_with_kb_id = derived.get("with_kb_id")
        if not as_kb_id:
            as_kb_id = session_as_kb_id
        if not with_kb_id:
            with_kb_id = session_with_kb_id

        if not as_kb_id:
            raise ValidationError(
                "no character found in session — specify --as <kb.id> to identify "
                "who the AI voices"
            )

        is_direct_turn = (
            with_kb_id is not None
            and as_kb_id == session_as_kb_id
            and with_kb_id == session_with_kb_id
        )
        with_line_mode = _WITH_LINE_MODE_DIRECT if is_direct_turn else _WITH_LINE_MODE_ASIDE

        if retry:
            # Check whether the pending transaction is the atomic fresh-session
            # setup (sub-node creation + parent annotation + first AI turn, all
            # unstaged in one transaction).  The first turn is written with a
            # closed annotation, so run_inline's open-annotation scan would find
            # nothing and raise "no pending chat transaction to retry".  Instead,
            # roll back the whole transaction and re-run the fresh session.
            if node.key_path:
                probe_storage = session.new_storage()
                if probe_storage.has_pending():
                    session_id = node.key_path[-1]
                    parent = NarrativeNode(
                        narrative_root=node.narrative_root,
                        key_path=node.key_path[:-1],
                    )
                    parent_rel = str(parent.md_path().relative_to(session.git_root))
                    expected_owner = cls.owner_id(session_id, parent_rel)
                    if probe_storage.detect_pending_owner() == expected_owner:
                        # Read session params from parent annotation before rollback.
                        parent_text = parent.md_path().read_text(encoding="utf-8")
                        saved_prompt: str | None = None
                        saved_pins: list[str] = []
                        for ann in reversed(parse_annotations(parent_text)):
                            if ann.operator == cls.name and ann.id == session_id:
                                p = ann.params.get("prompt")
                                if p:
                                    saved_prompt = str(p)
                                kb_pin = ann.params.get("kb_pin")
                                if isinstance(kb_pin, list):
                                    saved_pins = [str(p) for p in cast(list[object], kb_pin)]
                                elif isinstance(kb_pin, str):
                                    saved_pins = [kb_pin]
                                break
                        probe_storage.rollback()
                        fresh_cursor = narrative.find_cursor()
                        result = await cls._start_fresh_session(
                            session=session,
                            narrative=narrative,
                            cursor=fresh_cursor,
                            as_kb_id=as_kb_id or "",
                            with_kb_id=with_kb_id,
                            prompt=saved_prompt,
                            pins=saved_pins,
                            llm_id=llm_id,
                            reasoning=reasoning,
                            slug=None,
                            on_token=on_token,
                            on_stream_target=None,
                            cancel_event=cancel_event,
                            workflow=cast(WorkflowRunner | None, kwargs.get("workflow")),
                        )
                        await cls._run_post_inline_hooks(
                            session=session,
                            narrative=narrative,
                            cursor=fresh_cursor,
                            on_token=on_token,
                            cancel_event=cancel_event,
                            on_status=on_status,
                            on_info_event=on_info_event,
                        )
                        return result

            if module_ids or pins or unpins:
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
                    node, module_ids, pins, unpins, fm_storage, session
                )
            inline_ep: dict[str, Any] = {
                "as_kb_id": as_kb_id,
                "with_kb_id": with_kb_id,
                "with_line_mode": with_line_mode,
            }
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
                extra_params=inline_ep,
                cancel_event=cancel_event,
                on_status=on_status,
                on_info_event=on_info_event,
                empty_prompt_ok=True,
                workflow=kwargs.get("workflow"),
            )
            return

        # Non-retry: stage pending, apply front-matter changes, append user line.
        probe_storage = session.new_storage()
        if probe_storage.has_pending():
            probe_storage.stage_all()

        if module_ids or pins or unpins:
            fm_storage = session.new_storage()
            cls._update_front_matter_for_call(
                node, module_ids, pins, unpins, fm_storage, session
            )
            fm_storage.stage_all()

        session_mentions, session_includes = cls.session_mention_ids(kwargs)

        # Session speaker turns answer the counterpart line. One-off
        # interjections instead treat the prompt as third-person stage directions.
        inline_ep2: dict[str, Any] = {
            "as_kb_id": as_kb_id,
            "with_kb_id": with_kb_id,
            "with_line_mode": with_line_mode,
        }
        if prompt and is_direct_turn:
            await cls._run_direct_with_turn(
                session=session,
                narrative=narrative,
                node=node,
                user_prompt=prompt,
                with_kb_id=with_kb_id,
                as_kb_id=as_kb_id,
                with_line_mode=with_line_mode,
                narrate=narrate,
                wait=wait,
                llm_id=llm_id,
                reasoning=reasoning,
                on_token=on_token,
                cancel_event=cancel_event,
                mentions=session_mentions,
                includes=session_includes,
                workflow=cast(WorkflowRunner | None, kwargs.get("workflow")),
            )
            await cls._run_post_inline_hooks(
                session=session,
                narrative=narrative,
                cursor=node,
                on_token=on_token,
                cancel_event=cancel_event,
                on_status=on_status,
                on_info_event=on_info_event,
            )
        else:
            await cls.run_inline(
                session=session,
                narrative=narrative,
                prompt=prompt,
                pins=[],
                unpins=[],
                llm_id=llm_id,
                reasoning=reasoning,
                retry=False,
                mentions=session_mentions,
                includes=session_includes,
                on_token=on_token,
                _cursor_override=node,
                extra_params=inline_ep2,
                cancel_event=cancel_event,
                on_status=on_status,
                on_info_event=on_info_event,
                empty_prompt_ok=True,
                workflow=kwargs.get("workflow"),
            )
