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
from typing import Any, ClassVar, cast

from lens.core.annotations import strip_markdown_comments
from lens.core.knowledge import validate_ids_exist
from lens.core.context import crawl
from lens.core.llm import generate_stream
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operator import Operator
from lens.core.storage import Storage
from lens.core.pinning import pin as pin_to_node, unpin as unpin_at_node
from lens.core.project import ProjectSession, validate_slug
from lens.core.tools import OperatorToolDef, register_operator_tool

from lens.core.operators.session import (
    SUMMARY_SYSTEM_PROMPT as SYSTEM_PROMPT,
    SUMMARY_INSTRUCTION_TEMPLATE,
)


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
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        return SUMMARY_INSTRUCTION_TEMPLATE.format(content=params.get("content", ""))

    def start(
        self,
        id: str,
        pins: list[str] | None = None,
        unpins: list[str] | None = None,
        chain: dict[str, object] | None = None,
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
        if chain:
            params["chain"] = chain
        child = self.create_subnode(cursor, id, params=params if params else None)
        if pins:
            pin_to_node(child, pins, self.storage)
        if unpins:
            unpin_at_node(child, unpins, self.storage)
        return child

    async def end(self, session: ProjectSession, llm_id: str | None = None, on_token: Callable[[str], Awaitable[None]] | None = None, cancel_event: asyncio.Event | None = None) -> None:
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

        crawl_result = crawl(parent)
        messages = self.build_messages(crawl_result, {"content": child_clean})

        summary = ""
        interrupted = False
        try:
            async for event in generate_stream(
                messages, session.project_root, llm_id=llm_id,
                cancel_event=cancel_event,
            ):
                if event.preview:
                    if on_token:
                        await on_token(event.preview)
                if event.final:
                    if event.final.interrupted:
                        interrupted = True
                        break
                    summary = event.final.text.strip()
                    break
        except KeyboardInterrupt:
            interrupted = True

        if interrupted:
            raise KeyboardInterrupt
        if not summary:
            raise ValueError("LLM returned no summary content")

        self.close_subnode(parent, key, summary)

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
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> str:
        cursor = narrative.find_cursor()
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
        await op.end(session, llm_id=llm_id, on_token=on_token, cancel_event=cancel_event)
        return key


# ---------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------


def _section_invoke(
    args: dict[str, object],
    session: ProjectSession,
    narrative: NarrativeNode,
    storage: Storage | None = None,
) -> NarrativeNode:
    id_val = args.get("id")
    if not isinstance(id_val, str) or not id_val:
        raise ValueError("section tool requires non-empty 'id'")
    raw_pins = args.get("kb_pin")
    pins: list[str] = (
        [x for x in raw_pins if isinstance(x, str)]  # pyright: ignore[reportUnknownVariableType]
        if isinstance(raw_pins, list)
        else []
    )
    raw_unpins = args.get("kb_unpin")
    unpins: list[str] = (
        [x for x in raw_unpins if isinstance(x, str)]  # pyright: ignore[reportUnknownVariableType]
        if isinstance(raw_unpins, list)
        else []
    )
    if pins or unpins:
        validate_ids_exist(session.project_root, pins + unpins)
    cursor = narrative.find_cursor()
    rel_path = str(cursor.md_path().relative_to(session.git_root))
    owner = SectionOperator.owner_id(id_val, rel_path)
    st = storage if storage is not None else session.new_storage(owner=owner)
    op = SectionOperator(st, narrative)
    raw_chain = args.get("chain")
    chain_for_ann: dict[str, object] | None = (
        cast(dict[str, object], raw_chain) if isinstance(raw_chain, dict) else None
    )
    return op.start(id_val, pins=pins, unpins=unpins, chain=chain_for_ann)


async def _section_tool_invoke(
    args: dict[str, object],
    session: ProjectSession,
    narrative: NarrativeNode,
    depth: int,
    on_token: Callable[[str], Awaitable[None]] | None,
    on_confirm: Callable[[str, str], Awaitable[bool]] | None,
    *,
    storage: Storage | None = None,
    cursor: NarrativeNode | None = None,
) -> NarrativeNode | None:
    return _section_invoke(args, session, narrative, storage=storage)


register_operator_tool(
    "section",
    OperatorToolDef(
        parameters={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Section ID (alphanumeric, underscores, hyphens)",
                },
                "kb_pin": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "KB IDs to pin in the new section's front matter",
                },
                "kb_unpin": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "KB IDs to unpin in the new section's front matter",
                },
            },
            "required": ["id"],
        },
        prompt_snippet=(
            "Use the 'section' tool when starting a new scene, location, or narrative unit. "
            "Provide 'id' (section key, e.g. castle-dorn). Use 'kb_pin' to pin knowledge objects "
            "(locations, factions, NPCs) that apply to this section. Use 'kb_unpin' to cancel "
            "ancestor pins that no longer apply."
        ),
        keep_text=True,
    ),
    _section_tool_invoke,
)
