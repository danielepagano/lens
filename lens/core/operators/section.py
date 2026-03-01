"""Section operator: create and close child narrative nodes.

``lens section start <id>`` creates a child node at the cursor and opens a
``[section:id]: #`` annotation in the parent.

``lens section end`` closes the current section by generating an LLM summary
and appending it with the closing annotation tag.

``lens section range <id> <address> <start_line> <end_line>`` creates a section
"after the fact": the selected line range is moved into a new child node,
a summary is generated, and the range is replaced with the section annotation.
The operation is one-shot and fully reversible via ``lens rollback``.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Awaitable
from typing import Any, ClassVar, cast

from lens.core.address import NarrativeAddress
from lens.core.annotations import find_front_matter_span, strip_markdown_comments
from lens.core.knowledge import validate_ids_exist
from lens.core.context import CrawlResult, crawl
from lens.core.llm import generate_stream
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation, parse_segments
from lens.core.chain import ChainSpec
from lens.core.operator import Operator
from lens.core.storage import Storage
from lens.core.pinning import pin as pin_to_node, unpin as unpin_at_node
from lens.core.project import ProjectSession, resolve_address, validate_slug
from lens.core.tools import OperatorToolDef, register_operator_tool

SYSTEM_PROMPT = (
    "You are a skilled editor. Write a concise summary of the provided section,"
    " preserving the author's voice and style."
)

SUMMARY_INSTRUCTION_TEMPLATE = (
    "The section below has just been written and is now being closed.\n"
    "Write a brief summary that:\n"
    "- reads fluently as a continuation of the current passage above\n"
    "- represents the key consequences and outcomes described in the section\n"
    "- matches the voice and style of the surrounding narrative\n\n"
    "Output only the summary text — no preamble, no meta-commentary.\n\n"
    "SECTION TO SUMMARIZE:\n{content}"
)


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

    async def end(self, session: ProjectSession, llm_id: str | None = None, on_token: Callable[[str], Awaitable[None]] | None = None) -> None:
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
                messages, session.project_root, llm_id=llm_id
            ):
                if event.preview:
                    if on_token:
                        await on_token(event.preview)
                    else:
                        print(event.preview, end="", flush=True)
                if event.final:
                    if event.final.interrupted:
                        interrupted = True
                        break
                    summary = event.final.text.strip()
                    break
        except KeyboardInterrupt:
            interrupted = True
        if on_token is None:
            print()

        if interrupted:
            raise KeyboardInterrupt
        if not summary:
            raise ValueError("LLM returned no summary content")

        self.close_subnode(parent, key, summary)

    async def section_range(
        self,
        target_node: NarrativeNode,
        id: str,
        start_line: int,
        end_line: int,
        session: ProjectSession,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Create a section after the fact by extracting a line range into a child node.

        Validates that the range does not cut through any annotation block or its
        content body. Any sub-nodes whose annotation lies fully inside the range are
        moved into the new child node's directory. The parent is rewritten with a
        section annotation wrapping the LLM-generated summary. The entire operation
        is a single unstaged transaction, reversible via rollback.
        """
        md_path = target_node.md_path()
        text = md_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        n_lines = len(lines)

        if start_line < 1 or end_line > n_lines or start_line > end_line:
            raise ValueError(
                f"line range {start_line}–{end_line} is out of bounds"
                f" (file has {n_lines} lines)"
            )

        if id in target_node.child_keys():
            raise ValueError(f"section '{id}' already exists in this node")

        # Validate that the range does not split any annotation block.
        # Each segment's full span (open tag through close tag) must lie
        # entirely inside or entirely outside the selected range.
        segments = parse_segments(text)
        subnodes_to_move: list[str] = []

        for seg in segments:
            ann = seg.annotation
            if ann is None:
                continue

            seg_first = ann.line_start

            if seg.close is None:
                # Unclosed annotation: cursor is in this sub-node (or the annotation
                # is still in progress). Treat its span as extending to end of file.
                seg_last = n_lines
                overlaps = seg_first <= end_line and seg_last >= start_line
                if overlaps:
                    raise ValueError(
                        f"line range overlaps unclosed [{ann.operator}"
                        + (f":{ann.id}" if ann.id else "")
                        + "] annotation — cannot section in-progress content"
                    )
                continue

            # line_end on ParsedAnnotation is numerically equal to 1-based inclusive
            # last line (same value as 0-based exclusive index), so it works directly
            # as an upper bound in the 1-based line range comparison.
            seg_last = seg.close.line_end

            overlaps = seg_first <= end_line and seg_last >= start_line
            fully_inside = seg_first >= start_line and seg_last <= end_line

            if overlaps and not fully_inside:
                raise ValueError(
                    f"line range would split [{ann.operator}"
                    + (f":{ann.id}" if ann.id else "")
                    + f"] block (lines {seg_first}–{seg_last})"
                )

            if fully_inside and ann.id is not None:
                child = target_node.child_node(ann.id)
                if child.exists():
                    subnodes_to_move.append(ann.id)

        # Validate that front matter (if present) is not split.
        fm_span = find_front_matter_span(text)
        if fm_span is not None:
            fm_first = fm_span[0] + 1  # 0-based → 1-based inclusive start
            fm_last = fm_span[1]       # 0-based exclusive == 1-based inclusive end
            overlaps = fm_first <= end_line and fm_last >= start_line
            fully_inside = fm_first >= start_line and fm_last <= end_line
            if overlaps and not fully_inside:
                raise ValueError("line range would split the front matter block")

        # Extract selected content (verbatim, including any annotations).
        selected_text = "\n".join(lines[start_line - 1 : end_line]).strip()

        # Generate LLM summary before touching the file system.
        child_clean = strip_markdown_comments(selected_text).strip()
        passage_before = strip_markdown_comments(
            "\n".join(lines[: start_line - 1])
        ).strip()

        crawl_result = crawl(target_node, extra_pins=pins, extra_unpins=unpins)
        adjusted_crawl = CrawlResult(
            knowledge=crawl_result.knowledge,
            previous_summaries=crawl_result.previous_summaries,
            current_content=passage_before or None,
        )
        messages = self.build_messages(adjusted_crawl, {"content": child_clean})

        summary = ""
        interrupted = False
        try:
            async for event in generate_stream(messages, session.project_root, llm_id=llm_id):
                if event.preview:
                    if on_token:
                        await on_token(event.preview)
                    else:
                        print(event.preview, end="", flush=True)
                if event.final:
                    if event.final.interrupted:
                        interrupted = True
                        break
                    summary = event.final.text.strip()
                    break
        except KeyboardInterrupt:
            interrupted = True
        if on_token is None:
            print()

        if interrupted:
            raise KeyboardInterrupt
        if not summary:
            raise ValueError("LLM returned no summary content")

        # Build the replacement block for the parent node.
        open_tag = self.build_open_tag(id)
        close_tag = self.build_close_tag(id)
        section_block = f"{open_tag}\n\n{summary}\n\n{close_tag}"

        before_lines = lines[: start_line - 1]
        after_lines = lines[end_line:]

        # Ensure blank line separation around the inserted block.
        if before_lines and before_lines[-1].strip():
            before_lines = before_lines + [""]
        if after_lines and after_lines[0].strip():
            after_lines = [""] + after_lines

        new_parent_text = "\n".join(before_lines + [section_block] + after_lines)

        # --- File system changes (single transaction) ---

        # Promote leaf to folder if needed; this is the first storage operation
        # and establishes transaction ownership.
        if target_node.is_leaf():
            target_node.to_folder(self.storage)

        # parent_md_dir is computed after potential promotion.
        parent_md_dir = target_node.md_path().parent
        child_dir = parent_md_dir / id

        self.storage.mkdir(child_dir)

        # Move any sub-nodes that lived in the selected range into the child directory.
        for sub_id in subnodes_to_move:
            sub_leaf = parent_md_dir / f"{sub_id}.md"
            sub_folder = parent_md_dir / sub_id
            if sub_leaf.exists():
                self.storage.rename(sub_leaf, child_dir / f"{sub_id}.md")
            elif sub_folder.is_dir():
                # shutil handles recursive directory moves; git add -A tracks the result.
                shutil.move(str(sub_folder), str(child_dir / sub_id))

        # Write child node content and updated parent.
        self.storage.write_file(child_dir / "_node.md", selected_text + "\n")
        self.storage.write_file(target_node.md_path(), new_parent_text)

    @classmethod
    async def run_start(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        id: str,
        pins: list[str] | None = None,
        unpins: list[str] | None = None,
        write_prompt: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_confirm: Callable[[str, str], Awaitable[bool]] | None = None,
    ) -> NarrativeNode:
        if not validate_slug(id):
            raise ValueError(f"invalid section ID '{id}' (alphanumeric, underscores, hyphens only)")
        cursor = narrative.find_cursor()
        rel = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(id, rel)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)
        child = op.start(id, pins=pins or [], unpins=unpins or [])
        if write_prompt is not None:
            chain_spec = ChainSpec(name="write", id=None, arguments={"prompt": write_prompt})
            await Operator._run_chained_operator(  # pyright: ignore[reportPrivateUsage]
                chain_spec=chain_spec,
                storage=storage,
                session=session,
                narrative=narrative,
                depth=0,
                on_token=on_token,
                on_confirm=on_confirm,
                cursor_override=child,
            )
        return child

    @classmethod
    async def run_end(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        llm_id: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        cursor = narrative.find_cursor()
        if not cursor.key_path:
            raise ValueError("no open section to close (cursor at root)")
        key = cursor.key_path[-1]
        parent = NarrativeNode(narrative_root=narrative.narrative_root, key_path=cursor.key_path[:-1])
        rel = str(parent.md_path().relative_to(session.git_root))
        owner = cls.owner_id(key, rel)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)
        await op.end(session, llm_id=llm_id, on_token=on_token)
        return key

    @classmethod
    async def run_range(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        id: str,
        address_str: str,
        start_line: int,
        end_line: int,
        pins: list[str] | None = None,
        unpins: list[str] | None = None,
        llm_id: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        if not validate_slug(id):
            raise ValueError(f"invalid section ID '{id}' (alphanumeric, underscores, hyphens only)")
        addr = NarrativeAddress.parse(address_str)
        resolved = resolve_address(addr, session.project_root)
        target_node = resolved.to_node(session.project_root)
        if not target_node.exists():
            raise ValueError(f"node does not exist: {address_str}")
        rel_path = str(target_node.md_path().relative_to(session.git_root))
        owner = cls.owner_id(id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)
        await op.section_range(
            target_node=target_node, id=id, start_line=start_line, end_line=end_line,
            session=session, pins=pins or [], unpins=unpins or [],
            llm_id=llm_id, on_token=on_token,
        )


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
