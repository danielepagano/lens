"""Section operator: create and close child narrative nodes.

``lens section <id>`` creates a child node at the cursor and opens a
``[section:id]: #`` annotation in the parent.

``lens section --end`` closes the current section by generating an LLM summary
and appending it with the closing annotation tag.

``lens section <id> <address> <start_line> <end_line>`` creates a section
"after the fact": the selected line range is moved into a new child node,
a summary is generated, and the range is replaced with the section annotation.
The operation is one-shot and fully reversible via ``lens rollback``.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import ClassVar

import typer

from lens.address import NarrativeAddress
from lens.annotations import find_front_matter_span, strip_markdown_comments
from lens.context import CrawlResult, assemble_prompt, crawl
from lens.llm import LLMError, generate
from lens.narrative import NarrativeNode, find_unclosed_cursor_annotation, parse_segments
from lens.operator import Operator
from lens.project import get_active_narrative, require_lens_context, resolve_address, validate_slug
from lens.storage import Storage

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

    def start(self, id: str) -> None:
        """Create a child node and open the section annotation."""
        cursor = self.narrative_root.find_cursor()
        if id in cursor.child_keys():
            raise ValueError(f"section '{id}' already exists")
        self.create_subnode(cursor, id)

    async def end(self, project_root: Path, llm_id: str | None = None) -> None:
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
        instruction = SUMMARY_INSTRUCTION_TEMPLATE.format(content=child_clean)
        messages = assemble_prompt(
            crawl_result,
            system_prompt=SYSTEM_PROMPT,
            instruction=instruction,
        )

        chunks: list[str] = []
        interrupted = False
        try:
            async for chunk in generate(messages, project_root, llm_id=llm_id):
                print(chunk, end="", flush=True)
                chunks.append(chunk)
        except KeyboardInterrupt:
            interrupted = True
        print()

        summary = "".join(chunks).strip()
        if not summary:
            raise ValueError("LLM returned no summary content")

        self.close_subnode(parent, key, summary)

        if interrupted:
            raise KeyboardInterrupt

    async def section_range(
        self,
        target_node: NarrativeNode,
        id: str,
        start_line: int,
        end_line: int,
        project_root: Path,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
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
        instruction = SUMMARY_INSTRUCTION_TEMPLATE.format(content=child_clean)
        messages = assemble_prompt(
            adjusted_crawl,
            system_prompt=SYSTEM_PROMPT,
            instruction=instruction,
        )

        chunks: list[str] = []
        interrupted = False
        try:
            async for chunk in generate(messages, project_root, llm_id=llm_id):
                print(chunk, end="", flush=True)
                chunks.append(chunk)
        except KeyboardInterrupt:
            interrupted = True
        print()

        summary = "".join(chunks).strip()
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

        if interrupted:
            raise KeyboardInterrupt


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------

app = typer.Typer(invoke_without_command=True, no_args_is_help=True)


@app.callback()
def section(
    id_or_end: str | None = typer.Argument(
        None,
        help="Section ID to start (alphanumeric, underscores, hyphens)",
    ),
    address: str | None = typer.Argument(
        None,
        help="Node address for after-the-fact sectioning",
    ),
    start_line: int | None = typer.Argument(
        None,
        help="First line of range to section (1-based, inclusive)",
    ),
    end_line: int | None = typer.Argument(
        None,
        help="Last line of range to section (1-based, inclusive)",
    ),
    end: bool = typer.Option(
        False,
        "--end",
        "-e",
        help="Close the current section",
    ),
    pin: list[str] = typer.Option(
        [],
        "--pin",
        "-p",
        help="KB ID to pin for this operator (repeatable)",
    ),
    unpin: list[str] = typer.Option(
        [],
        "--unpin",
        "-u",
        help="KB ID to unpin for this operator (repeatable)",
    ),
    llm: str | None = typer.Option(
        None,
        "--llm",
        "-l",
        help="LLM ID to use (overrides project default)",
    ),
) -> None:
    """Start a section at cursor, close the current section, or section a line range.

    \b
    lens section <id>                            start section at cursor
    lens section --end                           close current section
    lens section <id> <address> <start> <end>   section a line range after the fact
    """
    try:
        git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    narrative = get_active_narrative(project_root)
    if narrative is None:
        typer.echo("lens section: no active narrative (run 'lens use <slug>' first)", err=True)
        raise typer.Exit(1)

    if end:
        _section_end(git_root, project_root, narrative, llm_id=llm)
    elif address is not None or start_line is not None or end_line is not None:
        # After-the-fact range sectioning: all three extra args are required.
        if id_or_end is None or address is None or start_line is None or end_line is None:
            typer.echo(
                "lens section: after-the-fact mode requires: <id> <address> <start_line> <end_line>",
                err=True,
            )
            raise typer.Exit(1)
        _section_range(
            git_root,
            project_root,
            narrative,
            id=id_or_end.strip(),
            address=address,
            start_line=start_line,
            end_line=end_line,
            pins=list(pin),
            unpins=list(unpin),
            llm_id=llm,
        )
    else:
        if id_or_end is None:
            typer.echo("lens section: provide a section ID or use --end / -e", err=True)
            raise typer.Exit(1)
        _section_start(git_root, narrative, id_or_end.strip())


def _section_start(git_root: Path, narrative: NarrativeNode, id: str) -> None:
    if not id:
        typer.echo("Error: section ID cannot be empty.", err=True)
        raise typer.Exit(1)
    if not validate_slug(id):
        typer.echo(
            f"Error: invalid section ID '{id}' (alphanumeric, underscores, hyphens only)",
            err=True,
        )
        raise typer.Exit(1)

    cursor = narrative.find_cursor()
    cursor_md = cursor.md_path()
    rel = str(cursor_md.relative_to(git_root))
    owner = SectionOperator.owner_id(id, rel)
    storage = Storage(git_root, owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        op.start(id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Started section '{id}'")


def _section_end(
    git_root: Path,
    project_root: Path,
    narrative: NarrativeNode,
    llm_id: str | None = None,
) -> None:
    cursor = narrative.find_cursor()
    if not cursor.key_path:
        typer.echo("lens section --end: no open section to close (cursor at root)", err=True)
        raise typer.Exit(1)
    key = cursor.key_path[-1]
    parent_key_path = cursor.key_path[:-1]
    parent = NarrativeNode(
        narrative_root=narrative.narrative_root,
        key_path=parent_key_path,
    )
    parent_md = parent.md_path()
    rel = str(parent_md.relative_to(git_root))
    owner = SectionOperator.owner_id(key, rel)
    storage = Storage(git_root, owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        asyncio.run(op.end(project_root, llm_id=llm_id))
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens section --end: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens section --end: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo(f"Closed section '{key}'", err=True)


def _section_range(
    git_root: Path,
    project_root: Path,
    narrative: NarrativeNode,
    id: str,
    address: str,
    start_line: int,
    end_line: int,
    pins: list[str],
    unpins: list[str],
    llm_id: str | None,
) -> None:
    if not id:
        typer.echo("Error: section ID cannot be empty.", err=True)
        raise typer.Exit(1)
    if not validate_slug(id):
        typer.echo(
            f"Error: invalid section ID '{id}' (alphanumeric, underscores, hyphens only)",
            err=True,
        )
        raise typer.Exit(1)

    try:
        addr = NarrativeAddress.parse(address)
    except ValueError as e:
        typer.echo(f"lens section: invalid address: {e}", err=True)
        raise typer.Exit(1)

    try:
        resolved = resolve_address(addr, project_root)
        target_node = resolved.to_node(project_root)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)

    if not target_node.exists():
        typer.echo(f"lens section: node does not exist: {address}", err=True)
        raise typer.Exit(1)

    target_md = target_node.md_path()
    rel_path = str(target_md.relative_to(git_root))
    owner = SectionOperator.owner_id(id, rel_path)
    storage = Storage(git_root, owner=owner)
    op = SectionOperator(storage, narrative)

    try:
        asyncio.run(
            op.section_range(
                target_node=target_node,
                id=id,
                start_line=start_line,
                end_line=end_line,
                project_root=project_root,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
            )
        )
    except ValueError as e:
        typer.echo(f"lens section: {e}", err=True)
        raise typer.Exit(1)
    except LLMError as e:
        typer.echo(f"lens section: LLM error: {e}", err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\nlens section: interrupted", err=True)
        raise typer.Exit(1)
    typer.echo(f"Sectioned lines {start_line}–{end_line} into '{id}'", err=True)
