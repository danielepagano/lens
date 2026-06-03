"""Design operator: collaborative KB design workspace.

``lens design [PROMPT]`` opens a design session in its own sub-node the first
time it is called, or continues the current session if the cursor is already
inside one.

Session lifecycle
-----------------
*  First call → creates a sub-node with an auto-generated id
   (``design[-module][-prompt-slug]``), writes front matter with pins/unpins,
   and appends the first inline ``[design…]: # … [/design]: #`` block.
*  Subsequent calls inside the same session → append new inline blocks to the
   existing sub-node.  Front matter is updated when ``--module`` changes or
   new pins/unpins are supplied.
*  ``--end`` → runs ``kb_extract_from_text`` on the full sub-node content and
   writes the close tag ``[/design:<id>]: #`` to the parent.

Module handling
---------------
``--module <key>`` pins ``design.<key>`` in the sub-node front matter.  If the
KB contains ``<key>._template``, that id is pinned as well and is replaced when
``--module`` changes (e.g. ``location`` + ``location._template``; ``world`` adds
no extra pin when no template exists).  The LLM sees the module as RELEVANT
KNOWLEDGE and is instructed (via the system prompt) to treat it as a directive.
Only one module is active at a time: switching ``--module`` removes all
``design.*`` pins before adding the new one, and drops the previous type's
``._template`` companion if it was pinned.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from lens.core.annotations import ParsedAnnotation
from lens.core.commands.kb import KbExtractResult, kb_extract_from_text
from lens.core.context import crawl
from lens.core.generation_artifacts import GenerationArtifacts
from lens.core.llm import LLMError
from lens.core.llm_run import LlmRunRequest, run_llm
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operator import OperatorError, extract_annotation_content, build_feedback_messages
from lens.core.operators.session import SessionOperator
from lens.core.prompts import PromptStore
from lens.core.project import ProjectSession
from lens.core.storage import Storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class DesignOperator(SessionOperator):
    name: ClassVar[str] = "design"
    requires_id: ClassVar[bool] = True
    use_command_tools: ClassVar[bool] = True
    module_prefix: ClassVar[str] = "design."
    required_modalities: ClassVar[frozenset[str]] = frozenset(
        {"kb_fence", "tool_fence_awareness"}
    )

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("design.system")

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt") or "Follow the design module in RELEVANT KNOWLEDGE"
        return PromptStore(self.project_root).format("design.instruction", prompt=prompt)

    # ------------------------------------------------------------------
    # Core generation helper (command-tools flow)
    # ------------------------------------------------------------------

    @classmethod
    async def _run_generation(
        cls,
        *,
        op: "DesignOperator",
        storage: Storage,
        design_child: NarrativeNode,
        ann_params: dict[str, Any],
        existing_ann: ParsedAnnotation | None,
        session: ProjectSession,
        llm_id: str | None,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None,
        feedback_messages: list[dict[str, str]] | None = None,
        pre_retry_snapshot: str | None = None,
        workflow: Any | None = None,
    ) -> None:
        """Crawl *design_child*, generate with command tools, write to child.

        If *existing_ann* is None, writes a fresh inline block (open + content
        + close).  If *existing_ann* is provided (retry path), calls
        ``write_append`` instead.  *feedback_messages* are appended after the
        assembled prompt to provide a prior-answer / feedback turn pair.

        *pre_retry_snapshot*, when set with *existing_ann*, is full file text
        captured before ``write_discard``; it is restored on generation failure
        so a failed retry cannot leave the child file empty.
        """
        ann_pins = op.extract_list(ann_params, "kb_pin")
        ann_unpins = op.extract_list(ann_params, "kb_unpin")
        crawl_result = crawl(
            cls.crawl_spec(
                design_child,
                ann_params,
                session=session,
                narrative=op.narrative_root,
                extra_pins=ann_pins,
                extra_unpins=ann_unpins,
                storage=storage,
            )
        )

        def _restore_pre_retry() -> None:
            if pre_retry_snapshot is not None and existing_ann is not None:
                op.storage.write_file(design_child.md_path(), pre_retry_snapshot)

        ctx, resolved = op._modality_context(
            crawl_result,
            ann_params,
            session=session,
            narrative=op.narrative_root,
        )
        tools_payload, command_handlers = cls.merge_command_tools_for_generation(
            resolved, ctx, session.project_root, ann_params
        )

        artifacts = GenerationArtifacts()
        try:
            artifacts = await run_llm(
                LlmRunRequest(
                    project_root=session.project_root,
                    crawl_result=crawl_result,
                    operator=op,
                    params=ann_params,
                    messages_append=tuple(feedback_messages) if feedback_messages else (),
                    llm_id=llm_id,
                    tools=tools_payload,
                    command_tool_handlers=command_handlers,
                    resolved_modalities=resolved,
                    modality_context=ctx,
                    enable_thinking=True,
                    reasoning=reasoning,
                    cancel_event=cancel_event,
                    on_token=on_token,
                    on_stream_event=on_stream_event,
                    operator_name=cls.name,
                ),
            )
        except LLMError as e:
            _restore_pre_retry()
            raise OperatorError(f"LLM error: {e}") from e

        if artifacts.interrupted:
            if artifacts.has_content():
                artifacts, _refine_warnings = await cls.apply_modality_post_refine(
                    session,
                    artifacts,
                    resolved=resolved,
                    ctx=ctx,
                    workflow=workflow,
                    on_token=on_token,
                    cancel_event=cancel_event,
                )
                if existing_ann is not None:
                    op.write_append(design_child, existing_ann, artifacts=artifacts)
                else:
                    cls._write_inline_block(
                        storage, design_child, ann_params, artifacts, op
                    )
            else:
                _restore_pre_retry()
            return

        if not artifacts.has_content():
            _restore_pre_retry()
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
        if existing_ann is not None:
            op.write_append(design_child, existing_ann, artifacts=artifacts)
        else:
            cls._write_inline_block(storage, design_child, ann_params, artifacts, op)

    @staticmethod
    def _write_inline_block(
        storage: Storage,
        design_child: NarrativeNode,
        ann_params: dict[str, Any],
        artifacts: GenerationArtifacts,
        op: "DesignOperator",
    ) -> None:
        del storage
        inline_tag = op.build_open_tag(None, ann_params)
        op.write_start(design_child, inline_tag, artifacts=artifacts)

    # ------------------------------------------------------------------
    # SessionOperator hooks
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
        reasoning: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
        **kwargs: Any,
    ) -> KbExtractResult:
        ann_params: dict[str, Any] = {}
        if prompt:
            ann_params["prompt"] = prompt
            mention_ids = cls.mention_pins(prompt, session.project_root)
            if mention_ids:
                ann_params["kb_pin"] = mention_ids
        if reasoning:
            ann_params["reasoning"] = reasoning

        # Create a new storage whose owner is keyed to the inline annotation.
        child_rel_path = str(node.md_path().relative_to(session.git_root))
        ann_line = cls.ann_line_for_append(node.md_path().read_text(encoding="utf-8"))
        inline_owner = cls.owner_id(None, child_rel_path, line=ann_line)
        inline_storage = session.new_storage(owner=inline_owner)
        inline_op = cls(inline_storage, narrative)

        await cls._run_generation(
            op=inline_op,
            storage=inline_storage,
            design_child=node,
            ann_params=ann_params,
            existing_ann=None,
            session=session,
            llm_id=llm_id,
            reasoning=reasoning,
            on_token=on_token,
            on_stream_event=kwargs.get("on_stream_event"),
            cancel_event=cancel_event,
            workflow=kwargs.get("workflow"),
        )
        return KbExtractResult()

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
        cancel_event: asyncio.Event | None,
        **kwargs: Any,
    ) -> KbExtractResult:
        probe_storage = session.new_storage()

        if retry:
            # Locate the last inline annotation and verify ownership.
            has_pending = probe_storage.has_pending()
            pending_owner = probe_storage.detect_pending_owner() if has_pending else None

            probe_op = cls(probe_storage, narrative)
            existing_ann = probe_op.find_open_annotation(node)
            if existing_ann is None:
                raise OperatorError("no design annotation found to retry")

            child_rel_path = str(node.md_path().relative_to(session.git_root))
            ann_owner = cls._owner_for_ann(existing_ann, child_rel_path)
            is_owner = (pending_owner == ann_owner) if has_pending else False
            if not is_owner:
                raise OperatorError("no pending design transaction to retry")

            storage = session.new_storage(owner=ann_owner)
            op = cls(storage, narrative)

            # When a prompt is provided on --retry, treat it as feedback:
            # capture the previous output and add a prior-answer/feedback turn.
            feedback = prompt
            previous_content: str | None = None
            if feedback:
                previous_content = extract_annotation_content(
                    node.md_path(), existing_ann
                )

            new_params: dict[str, Any] = dict(existing_ann.params)
            # Do NOT replace the stored prompt — feedback is a message turn.
            if reasoning:
                new_params["reasoning"] = reasoning

            # Update front matter before discard so context reflects new module.
            if module_id or pins or unpins:
                cls._update_front_matter_for_call(
                    node, module_id, pins, unpins, storage, session
                )

            pre_retry_snapshot = node.md_path().read_text(encoding="utf-8")
            op.write_discard(node, existing_ann, updated_params=new_params)

            fresh_ann = op.find_open_annotation(node)
            if fresh_ann is None:
                op.storage.write_file(node.md_path(), pre_retry_snapshot)
                raise OperatorError("lost annotation after discard")

            feedback_messages: list[dict[str, str]] | None = None
            if feedback and previous_content:
                feedback_messages = build_feedback_messages(previous_content, feedback, session.project_root)

            await cls._run_generation(
                op=op,
                storage=storage,
                design_child=node,
                ann_params=new_params,
                existing_ann=fresh_ann,
                session=session,
                llm_id=llm_id,
                reasoning=new_params.get("reasoning"),
                on_token=on_token,
                on_stream_event=kwargs.get("on_stream_event"),
                cancel_event=cancel_event,
                feedback_messages=feedback_messages,
                pre_retry_snapshot=pre_retry_snapshot,
                workflow=kwargs.get("workflow"),
            )
        else:
            # Auto-stage any pending transaction before a fresh inline block.
            if probe_storage.has_pending():
                probe_storage.stage_all()

            # Apply front-matter changes with a system-level storage, then
            # stage them so the generation starts from a clean state.
            if module_id or pins or unpins:
                fm_storage = session.new_storage()
                cls._update_front_matter_for_call(
                    node, module_id, pins, unpins, fm_storage, session
                )
                fm_storage.stage_all()

            ann_params: dict[str, Any] = {}
            if prompt:
                ann_params["prompt"] = prompt
                mention_ids = cls.mention_pins(prompt, session.project_root)
                if mention_ids:
                    ann_params["kb_pin"] = mention_ids
            if reasoning:
                ann_params["reasoning"] = reasoning

            child_rel_path = str(node.md_path().relative_to(session.git_root))
            ann_line = cls.ann_line_for_append(node.md_path().read_text(encoding="utf-8"))
            owner = cls.owner_id(None, child_rel_path, line=ann_line)
            storage = session.new_storage(owner=owner)
            op = cls(storage, narrative)

            await cls._run_generation(
                op=op,
                storage=storage,
                design_child=node,
                ann_params=ann_params,
                existing_ann=None,
                session=session,
                llm_id=llm_id,
                reasoning=reasoning,
                on_token=on_token,
                on_stream_event=kwargs.get("on_stream_event"),
                cancel_event=cancel_event,
                workflow=kwargs.get("workflow"),
            )

        return KbExtractResult()

    # ------------------------------------------------------------------
    # End session (KB extraction)
    # ------------------------------------------------------------------

    @classmethod
    async def run_session_end(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        llm_id: str | None = None,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
        summary_guidance: str | None = None,
        workflow: Any | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> KbExtractResult:
        """Close the current design session.

        Cursor must be in the design sub-node.  Runs ``kb_extract_from_text``
        on the full sub-node content and appends ``[/design:<id>]: #`` to the
        parent.
        """
        cursor = narrative.find_cursor()
        if not cursor.key_path:
            raise OperatorError("no open design to close (cursor at root)")
        id = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=cursor.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        parent_text = parent.md_path().read_text(encoding="utf-8")
        open_ann = find_unclosed_cursor_annotation(parent_text)
        if open_ann is None or open_ann.operator != cls.name or open_ann.id != id:
            raise OperatorError(
                f"parent does not have unclosed [design:{id}]: # — "
                "cursor must be in the design sub-node"
            )
        child_text = cursor.md_path().read_text(encoding="utf-8")
        rel_path = str(parent.md_path().relative_to(session.git_root))
        owner = cls.owner_id(id, rel_path)
        storage = session.new_storage(owner=owner)
        if storage.has_pending() and storage.detect_pending_owner() == owner:
            storage.stage_all()
        op = cls(storage, narrative)
        result = kb_extract_from_text(child_text, session.project_root, storage)
        for err in result.errors:
            logger.warning("design end: %s", err)
        op.append_to_node(parent, op.build_close_tag(id) + "\n")
        return result

    # ------------------------------------------------------------------
    # Backward-compatible entry point
    # ------------------------------------------------------------------

    @classmethod
    async def run_design(
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
        on_stream_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> KbExtractResult:
        """Run a design session (create, continue, or end).

        Delegates to :meth:`~SessionOperator.run_session`.
        """
        result = await cls.run_session(
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
            on_stream_event=on_stream_event,
            cancel_event=cancel_event,
        )
        return result if isinstance(result, KbExtractResult) else KbExtractResult()
