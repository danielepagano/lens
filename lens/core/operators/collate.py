"""Collate operator: section a line range at an arbitrary address (after the fact)."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable, Awaitable
from typing import ClassVar, Any

from lens.core.address import NarrativeAddress
from lens.core.annotations import (
    ParsedAnnotation,
    find_front_matter_span,
    strip_markdown_comments,
)
from lens.core.context import crawl
from lens.core.narrative import NarrativeNode, parse_segments
from lens.core.operator import Operator
from lens.core.operator_params import apply_pinned_invocation
from lens.core.project import ProjectSession, resolve_address, validate_slug
from lens.core.speech.tts_cache_sync import (
    migrate_collate_verbatim_audio,
    move_tts_cache_subtree,
    text_has_tts_cached,
)
from lens.core.storage import Storage

from lens.core.operators.section import (
    SectionOperator,
    section_close_tag,
    section_open_tag,
)
from lens.core.workflow_runner import (
    StepResult,
    WorkflowOutcome,
    WorkflowRunner,
    WorkflowStepDef,
    finalize_workflow_outcome,
)
from lens.core.workflow_summarize import SummarizeRememberState, build_summarize_remember_steps

# After the fact, session-style operators (see :mod:`lens.core.commands.rewind`)
# are not narrative sub-nodes like ``section`` / ``design`` and may be cut
# through when collating. ``edit`` blocks are review artifacts — do not split
# them; accept or roll back the edit instead.
_COLLATE_SPLITTABLE_BODY_OPERATORS: frozenset[str] = frozenset(
    {"write", "play", "chat"}
)


def _collate_fence_stripping_annotation(
    ann: ParsedAnnotation, target_node: NarrativeNode
) -> bool:
    """True when *ann* may be cut through and its open/close tag lines dropped."""
    if ann.closing or ann.self_closing:
        return False
    if ann.operator not in _COLLATE_SPLITTABLE_BODY_OPERATORS:
        return False
    if ann.id is not None and target_node.child_node(ann.id).exists():
        return False
    return True


def _collate_lines_without_fence_drops(
    lines: list[str],
    start_line: int,
    end_line: int,
    drop_line_nums: set[int],
) -> tuple[list[str], list[str], list[str]]:
    """Split *lines* into before / selected / after, omitting dropped 1-based indices."""
    before = [lines[i - 1] for i in range(1, start_line) if i not in drop_line_nums]
    selected = [
        lines[i - 1] for i in range(start_line, end_line + 1) if i not in drop_line_nums
    ]
    after = [
        lines[i - 1] for i in range(end_line + 1, len(lines) + 1) if i not in drop_line_nums
    ]
    return before, selected, after


class CollateOperator(Operator):
    """Operator that moves a line range into a new section child node (after-the-fact sectioning)."""

    name: ClassVar[str] = "collate"
    requires_id: ClassVar[bool] = True

    # Collate does not use the Operator prompt flow. It reuses the shared
    # generate_summary_block() helper (same system prompt and instruction
    # template as section end). These stubs only satisfy the Operator ABC.
    @property
    def system_prompt(self) -> str:
        return ""

    def build_instruction(self, params: dict[str, object]) -> str:
        return ""

    async def _collate_range(
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
        cancel_event: asyncio.Event | None = None,
        reasoning: str | None = None,
        summary_guidance: str | None = None,
        workflow: WorkflowRunner | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> WorkflowOutcome:
        md_path = target_node.md_path()
        text = md_path.read_text(encoding="utf-8")
        parent_had_tts = text_has_tts_cached(text)
        lines = text.split("\n")
        n_lines = len(lines)

        if start_line < 1 or end_line > n_lines or start_line > end_line:
            raise ValueError(
                f"line range {start_line}–{end_line} is out of bounds"
                f" (file has {n_lines} lines)"
            )

        if id in target_node.child_keys():
            raise ValueError(f"section '{id}' already exists in this node")

        segments = parse_segments(text)
        subnodes_to_move: list[str] = []
        drop_fence_lines: set[int] = set()

        for seg in segments:
            ann = seg.annotation
            if ann is None:
                continue

            seg_first = ann.line_start

            if seg.close is None:
                seg_last = n_lines
                overlaps = seg_first <= end_line and seg_last >= start_line
                if overlaps:
                    raise ValueError(
                        f"line range overlaps unclosed [{ann.operator}"
                        + (f":{ann.id}" if ann.id else "")
                        + "] annotation — cannot section in-progress content"
                    )
                continue

            seg_last = seg.close.line_end
            overlaps = seg_first <= end_line and seg_last >= start_line
            fully_inside = seg_first >= start_line and seg_last <= end_line

            if overlaps and not fully_inside:
                if not _collate_fence_stripping_annotation(ann, target_node):
                    raise ValueError(
                        f"line range would split [{ann.operator}"
                        + (f":{ann.id}" if ann.id else "")
                        + f"] block (lines {seg_first}–{seg_last})"
                    )
                drop_fence_lines.update(range(ann.line_start, ann.line_end + 1))
                drop_fence_lines.update(
                    range(seg.close.line_start, seg.close.line_end + 1)
                )

            if fully_inside and ann.id is not None:
                child = target_node.child_node(ann.id)
                if child.exists():
                    subnodes_to_move.append(ann.id)

        fm_span = find_front_matter_span(text)
        if fm_span is not None:
            fm_first = fm_span[0] + 1
            fm_last = fm_span[1]
            overlaps = fm_first <= end_line and fm_last >= start_line
            fully_inside = fm_first >= start_line and fm_last <= end_line
            if overlaps and not fully_inside:
                raise ValueError("line range would split the front matter block")

        before_lines, selected_lines, after_lines = _collate_lines_without_fence_drops(
            lines, start_line, end_line, drop_fence_lines
        )

        selected_text = "\n".join(selected_lines).strip()

        child_clean = strip_markdown_comments(selected_text).strip()
        passage_before = strip_markdown_comments("\n".join(before_lines)).strip()

        sr_state = SummarizeRememberState(slug=id, content=child_clean)

        narrative_root = NarrativeNode(
            narrative_root=target_node.narrative_root,
            key_path=(),
        )

        def prepare_crawl() -> Any:
            return crawl(
                CollateOperator.crawl_spec(
                    target_node,
                    {"id": id},
                    session=session,
                    narrative=narrative_root,
                    extra_pins=pins,
                    extra_unpins=unpins,
                    storage=self.storage,
                    current_passage_override=passage_before or "",
                )
            )

        async def run_persist() -> StepResult:
            open_tag = section_open_tag(id)
            close_tag = section_close_tag(id)
            section_block = f"{open_tag}\n\n{sr_state.summary}\n\n{close_tag}"

            bl = list(before_lines)
            al = list(after_lines)
            if bl and bl[-1].strip():
                bl = bl + [""]
            if al and al[0].strip():
                al = [""] + al

            new_parent_text = "\n".join(bl + [section_block] + al)

            migrate_collate_verbatim_audio(
                session.project_root,
                parent_node=target_node,
                child_node=target_node.child_node(id),
                selected_text=selected_text,
                parent_had_tts=parent_had_tts,
            )

            if target_node.is_leaf():
                target_node.to_folder(self.storage)

            parent_md_dir = target_node.md_path().parent
            child_content = selected_text + "\n"
            if sr_state.remember_suffix:
                child_content = child_content.rstrip("\n") + sr_state.remember_suffix

            if subnodes_to_move:
                child_dir = parent_md_dir / id
                self.storage.mkdir(child_dir)
                for sub_id in subnodes_to_move:
                    sub_leaf = parent_md_dir / f"{sub_id}.md"
                    sub_folder = parent_md_dir / sub_id
                    if sub_leaf.exists():
                        self.storage.rename(sub_leaf, child_dir / f"{sub_id}.md")
                    elif sub_folder.is_dir():
                        try:
                            sub_raw = (sub_folder / "_node.md").read_text(encoding="utf-8")
                        except OSError:
                            sub_raw = ""
                        sub_had_tts = text_has_tts_cached(sub_raw)
                        old_n = NarrativeNode(
                            narrative_root=target_node.narrative_root,
                            key_path=target_node.key_path + (sub_id,),
                        )
                        new_n = NarrativeNode(
                            narrative_root=target_node.narrative_root,
                            key_path=target_node.key_path + (id, sub_id),
                        )
                        move_tts_cache_subtree(
                            session.project_root,
                            old_n,
                            new_n,
                            old_had_tts=sub_had_tts,
                        )
                        shutil.move(str(sub_folder), str(child_dir / sub_id))
                self.storage.write_file(child_dir / "_node.md", child_content)
            else:
                self.storage.write_file(parent_md_dir / f"{id}.md", child_content)

            self.storage.write_file(target_node.md_path(), new_parent_text)
            return StepResult(ok=True)

        steps = build_summarize_remember_steps(
            sr_state,
            session=session,
            cursor=target_node,
            operator_name=self.name,
            llm_id=llm_id,
            reasoning=reasoning,
            on_token=on_token,
            cancel_event=cancel_event,
            storage=self.storage,
            system_key="session.summary_system",
            instruction_key="session.summary_instruction_template",
            summary_guidance=summary_guidance,
            summarize_should_run=lambda: bool(child_clean),
            prepare_crawl=prepare_crawl,
            operator=CollateOperator,
            operator_params={"id": id},
            narrative=narrative_root,
        )
        steps.append(
            WorkflowStepDef(
                id="collate_persist",
                label="Collating…",
                run=run_persist,
                abort_rolls_back=True,
            )
        )

        runner = workflow or WorkflowRunner(
            session=session,
            cancel_event=cancel_event,
            on_status=on_status,
        )
        outcome = await runner.run(steps, emit_plan=workflow is None)
        return finalize_workflow_outcome(session, outcome)

    @classmethod
    async def run_collate(
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
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
        summary_guidance: str | None = None,
        workflow: WorkflowRunner | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> Storage:
        if not validate_slug(id):
            raise ValueError(f"invalid section ID '{id}' (alphanumeric, underscores, hyphens only)")
        addr = NarrativeAddress.parse(address_str)
        resolved = resolve_address(addr, session.project_root)
        target_node = resolved.to_node(session.project_root)
        if not target_node.exists():
            raise ValueError(f"node does not exist: {address_str}")
        llm_id, reasoning, _ = apply_pinned_invocation(
            slug=cls.name,
            project_root=session.project_root,
            focus_node=target_node,
            narrative=None,
            llm_id=llm_id,
            reasoning=reasoning,
            extra_params=None,
        )
        rel_path = str(target_node.md_path().relative_to(session.git_root))
        # Collate emits ``[section:id]`` / ``[/section:id]`` on the parent; pending
        # owner detection reads those as operator ``section``. Match that owner so
        # ``Storage._ensure_ownership`` does not auto-stage mid-operation.
        owner = SectionOperator.owner_id(id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)
        outcome = await op._collate_range(
            target_node=target_node,
            id=id,
            start_line=start_line,
            end_line=end_line,
            session=session,
            pins=pins or [],
            unpins=unpins or [],
            llm_id=llm_id,
            on_token=on_token,
            cancel_event=cancel_event,
            reasoning=reasoning,
            summary_guidance=summary_guidance,
            workflow=workflow,
            on_status=on_status,
        )
        if outcome.rollback_pending or outcome.interrupted or outcome.kind == "cancelled":
            from lens.core.exceptions import OperatorError

            raise OperatorError("collate aborted")
        return storage
