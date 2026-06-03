"""Section operator: create and close child narrative nodes at the cursor.

``lens section <id>`` creates a child node at the cursor and opens a
``[section:id]: #`` annotation in the parent.

``lens section --end`` closes the current section by generating an LLM summary
and appending it with the closing annotation tag.

For after-the-fact sectioning (moving a line range into a new child node
elsewhere), use the collate operator: ``lens collate <id> <address> <start_line> <end_line>``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable
from typing import Any, ClassVar

from lens.core.annotations import strip_markdown_comments
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operator import Operator
from lens.core.operator_params import apply_pinned_invocation
from lens.core.pinning import pin as pin_to_node, unpin as unpin_at_node
from lens.core.project import ProjectSession, validate_slug
from lens.core.prompts import PromptStore
from lens.core.workflow_runner import StepResult, WorkflowOutcome, WorkflowRunner, WorkflowStepDef, finalize_workflow_outcome
from lens.core.workflow_summarize import SummarizeRememberState, build_summarize_remember_steps


def section_open_tag(id: str) -> str:
    """Return section open annotation string, e.g. ``[section:ch1]: #``."""
    return f"[section:{id}]: #"


def section_close_tag(id: str) -> str:
    """Return section close annotation string, e.g. ``[/section:ch1]: #``."""
    return f"[/section:{id}]: #"


class SectionOperator(Operator):
    name: ClassVar[str] = "section"
    requires_id: ClassVar[bool] = True

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("session.summary_system")

    def build_instruction(self, params: dict[str, Any]) -> str:
        return PromptStore(self.project_root).format(
            "session.summary_instruction_template",
            content=params.get("content", ""),
            slug=params.get("slug", ""),
        )

    def start(
        self,
        id: str,
        pins: list[str] | None = None,
        unpins: list[str] | None = None,
    ) -> NarrativeNode:
        """Create a child node and open the section annotation."""
        cursor = self.narrative_root.find_cursor()
        if id in cursor.child_keys():
            raise ValueError(f"section '{id}' already exists")
        params: dict[str, object] = {}
        if pins:
            params["kb_pin"] = pins
        if unpins:
            params["kb_unpin"] = unpins
        child = self.create_subnode(cursor, id, params=params if params else None)
        if pins:
            pin_to_node(child, pins, self.storage)
        if unpins:
            unpin_at_node(child, unpins, self.storage)
        return child

    async def end(
        self,
        session: ProjectSession,
        llm_id: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
        reasoning: str | None = None,
        summary_guidance: str | None = None,
        workflow: WorkflowRunner | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> WorkflowOutcome | None:
        """Close the current section by generating an LLM summary and appending it."""
        cursor = self.narrative_root.find_cursor()
        if not cursor.key_path:
            raise ValueError("no open section to close (cursor at root)")
        parent_key_path = cursor.key_path[:-1]
        key = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=self.narrative_root.narrative_root,
            key_path=parent_key_path,
        )
        text = parent.md_path().read_text(encoding="utf-8")
        ann = find_unclosed_cursor_annotation(text)
        if ann is None or ann.operator != "section" or ann.id != key:
            raise ValueError(
                f"parent does not have unclosed [section:{key}]: #"
            )

        child_text = cursor.md_path().read_text(encoding="utf-8")
        child_clean = strip_markdown_comments(child_text).strip()
        sr_state = SummarizeRememberState(slug=key, content=child_clean)

        async def run_close() -> StepResult:
            self.close_subnode(parent, key, sr_state.summary)
            if sr_state.remember_suffix:
                child_md = cursor.md_path()
                existing_child = child_md.read_text(encoding="utf-8")
                self.storage.write_file(
                    child_md, existing_child.rstrip("\n") + sr_state.remember_suffix
                )
            return StepResult(ok=True)

        steps = build_summarize_remember_steps(
            sr_state,
            session=session,
            cursor=cursor,
            operator_name=self.name,
            llm_id=llm_id,
            reasoning=reasoning,
            on_token=on_token,
            cancel_event=cancel_event,
            storage=self.storage,
            system_key="session.summary_system",
            instruction_key="session.summary_instruction_template",
            summary_guidance=summary_guidance,
            summarize_empty=True,
            operator=type(self),
            operator_params={},
            narrative=self.narrative_root,
        )
        steps.append(
            WorkflowStepDef(
                id="close",
                label="Closing section…",
                run=run_close,
            )
        )

        runner = workflow or WorkflowRunner(
            session=session,
            cancel_event=cancel_event,
            on_status=on_status,
        )
        outcome = await runner.run(steps)
        return finalize_workflow_outcome(session, outcome)

    @classmethod
    async def run_start(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        id: str,
        pins: list[str] | None = None,
        unpins: list[str] | None = None,
    ) -> NarrativeNode:
        if not validate_slug(id):
            raise ValueError(f"invalid section ID '{id}' (alphanumeric, underscores, hyphens only)")
        cursor = narrative.find_cursor()
        rel = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(id, rel)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)
        return op.start(id, pins=pins or [], unpins=unpins or [])

    @classmethod
    async def run_end(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        llm_id: str | None = None,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
        summary_guidance: str | None = None,
        workflow: WorkflowRunner | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> str:
        cursor = narrative.find_cursor()
        llm_id, reasoning, _ = apply_pinned_invocation(
            slug=cls.name,
            project_root=session.project_root,
            focus_node=cursor,
            narrative=narrative,
            llm_id=llm_id,
            reasoning=reasoning,
            extra_params=None,
        )
        if not cursor.key_path:
            raise ValueError("no open section to close (cursor at root)")
        key = cursor.key_path[-1]
        parent = NarrativeNode(narrative_root=narrative.narrative_root, key_path=cursor.key_path[:-1])
        rel = str(parent.md_path().relative_to(session.git_root))
        owner = cls.owner_id(key, rel)
        storage = session.new_storage(owner=owner)
        # Open-then-immediately-close: pending owner is still this section (no other
        # operator ran in between). Stage so that cancel + rollback does not delete the node.
        if storage.has_pending() and storage.detect_pending_owner() == owner:
            storage.stage_all()
        op = cls(storage, narrative)
        await op.end(
            session,
            llm_id=llm_id,
            on_token=on_token,
            cancel_event=cancel_event,
            reasoning=reasoning,
            summary_guidance=summary_guidance,
            workflow=workflow,
            on_status=on_status,
        )
        return key

