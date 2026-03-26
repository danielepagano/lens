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
from lens.core.command_tools import get_command_registry
from lens.core.commands.kb import KbExtractResult, kb_extract_from_text
from lens.core.context import assemble_prompt, crawl
from lens.core.llm import LLMError, generate_stream
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operator import OperatorError
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

    @classmethod
    def _companion_pin_for_module(
        cls, session: ProjectSession, module_key: str
    ) -> str | None:
        tid = f"{module_key}._template"
        return tid if session.kb.exists(tid) else None

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
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
    ) -> None:
        """Crawl *design_child*, generate with command tools, write to child.

        If *existing_ann* is None, writes a fresh inline block (open + content
        + close).  If *existing_ann* is provided (retry path), calls
        ``write_append`` instead.
        """
        crawl_result = crawl(design_child)
        instruction = op.build_instruction(ann_params)
        messages = assemble_prompt(
            crawl_result,
            system_prompt=op.system_prompt,
            instruction=instruction,
        )

        cmd_registry = get_command_registry()
        tools_payload = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": cmd_def.description,
                    "parameters": cmd_def.parameters,
                },
            }
            for name, (cmd_def, _) in cmd_registry.items()
        ]
        command_handlers = {name: fn for name, (_, fn) in cmd_registry.items()}

        content = ""
        interrupted = False
        try:
            async for event in generate_stream(
                messages,
                session.project_root,
                llm_id=llm_id,
                tools=tools_payload if tools_payload else None,
                command_tool_handlers=command_handlers if command_handlers else None,
                enable_thinking=True,
                cancel_event=cancel_event,
            ):
                if event.preview and on_token:
                    await on_token(event.preview)
                if event.final:
                    if event.final.interrupted:
                        interrupted = True
                        break
                    content = event.final.text
                    break
        except KeyboardInterrupt:
            interrupted = True
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if interrupted:
            if content.strip():
                if existing_ann is not None:
                    op.write_append(design_child, existing_ann, content)
                else:
                    cls._write_inline_block(storage, design_child, ann_params, content, op)
            return

        if not content.strip():
            raise OperatorError("no content generated")

        if existing_ann is not None:
            op.write_append(design_child, existing_ann, content)
        else:
            cls._write_inline_block(storage, design_child, ann_params, content, op)

    @staticmethod
    def _write_inline_block(
        storage: Storage,
        design_child: NarrativeNode,
        ann_params: dict[str, Any],
        content: str,
        op: "DesignOperator",
    ) -> None:
        inline_tag = op.build_open_tag(None, ann_params)
        close_tag = op.build_close_tag(None)
        child_md = design_child.md_path()
        existing = child_md.read_text(encoding="utf-8") if child_md.exists() else ""
        sep = "\n" if existing.endswith("\n") else "\n\n"
        storage.write_file(
            child_md,
            existing + sep + inline_tag + "\n\n" + content.rstrip() + "\n\n" + close_tag + "\n",
        )

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
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
        **kwargs: Any,
    ) -> KbExtractResult:
        ann_params: dict[str, Any] = {"steps": 1}
        if prompt:
            ann_params["prompt"] = prompt

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
            on_token=on_token,
            cancel_event=cancel_event,
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

            new_params: dict[str, Any] = dict(existing_ann.params)
            if prompt:
                new_params["prompt"] = prompt

            # Update front matter before discard so context reflects new module.
            if module_id or pins or unpins:
                cls._update_front_matter_for_call(
                    node, module_id, pins, unpins, storage, session
                )

            op.write_discard(node, existing_ann, updated_params=new_params)

            fresh_ann = op.find_open_annotation(node)
            if fresh_ann is None:
                raise OperatorError("lost annotation after discard")

            await cls._run_generation(
                op=op,
                storage=storage,
                design_child=node,
                ann_params=new_params,
                existing_ann=fresh_ann,
                session=session,
                llm_id=llm_id,
                on_token=on_token,
                cancel_event=cancel_event,
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

            ann_params: dict[str, Any] = {"steps": 1}
            if prompt:
                ann_params["prompt"] = prompt

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
                on_token=on_token,
                cancel_event=cancel_event,
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
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
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
        retry: bool = False,
        end: bool = False,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_stream_target: Callable[[str], Awaitable[None]] | None = None,
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
            retry=retry,
            end=end,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=cancel_event,
        )
        return result if isinstance(result, KbExtractResult) else KbExtractResult()
