"""Advance operator: pass the time, update fronts.

``lens advance [--days N]`` creates an ``advance-day-*`` sub-node and runs the
LLM with the ``design.front`` module. Active fronts are pulled into context
automatically via ``timeline.<id>+`` expansion on the ancestor chain. KB
updates and the timeline day counter apply only after ``lens advance --end``
(with the cursor in that sub-node). Use ``lens advance --retry`` to discard.

Dataset-gated: requires the ``rpg`` dataset.

Requirements: at least one ``timeline.*`` must be pinned on the node where you
start advance. The operator pins ``design.front`` on the advance sub-node; do
not add ``design.*`` pins to story nodes yourself (that conflicts with play).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any, ClassVar, cast

import yaml

from lens.core.exceptions import ValidationError
from lens.core.annotations import ParsedAnnotation
from lens.core.commands.kb import KbExtractResult, kb_extract_from_text
from lens.core.context import CrawlResult, SliceAnchor, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import LLMError
from lens.core.llm_run import LlmRunRequest, run_llm
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation, parse_segments
from lens.core.operator import Operator, OperatorError, extract_annotation_content, build_feedback_messages
from lens.core.operators.session import SummaryTitleError, format_summary_block
from lens.core.pinning import pin as pin_node
from lens.core.pinning import unpin as unpin_node
from lens.core.prompts import PromptStore
from lens.core.project import ProjectSession
from lens.core.storage import Storage

logger = logging.getLogger(__name__)

DESIGN_MODULE_PIN = "design.front"
DEFAULT_MESSAGE = " day(s) have passed."

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADVANCE_BLOCK_RE = re.compile(r"```advance\s*\n(.*?)\n```", re.DOTALL)
_DAY_COUNTER_RE = re.compile(r"^(- Day:\s*)(\d+)", re.MULTILINE)


def generate_advance_id(parent: NarrativeNode, current_day: int) -> str:
    """Generate ``advance-day-{current_day}`` based on the timeline day counter."""
    slug = f"advance-day-{current_day}"
    if slug in set(parent.child_keys()):
        raise ValidationError(
            f"advance session for day {current_day} ({slug}) already exists"
        )
    return slug


def _front_ids_from_pins(pinned_ids: list[str]) -> list[str]:
    """Extract sorted ``front.*`` base IDs from *pinned_ids* (stripping suffixes)."""
    return sorted({
        p.rstrip("+") for p in pinned_ids if p.startswith("front.")
    })


def generate_luck_rolls(front_ids: list[str]) -> dict[str, tuple[int, int]]:
    """Two random 1-100 rolls per front for chance mechanics."""
    return {fid: (random.randint(1, 100), random.randint(1, 100)) for fid in front_ids}


def parse_advance_result(
    content: str, requested_increment: int
) -> tuple[int, str]:
    """Parse the ``advance`` fenced block.

    Returns ``(days_elapsed, summary)`` where:
    - ``days_elapsed`` is clamped to [1, requested_increment]; defaults to
      the full increment if the block or field is absent.
    - ``summary`` is the narrative text from the ``summary`` field; falls
      back to ``"{days}{DEFAULT_MESSAGE}"`` if not present.
    """

    def _default(days: int) -> tuple[int, str]:
        return days, f"{days}{DEFAULT_MESSAGE}"

    match = _ADVANCE_BLOCK_RE.search(content)
    if not match:
        return _default(requested_increment)
    try:
        data: Any = yaml.safe_load(match.group(1))
        if not isinstance(data, dict):
            return _default(requested_increment)
        d = cast(dict[str, Any], data)
        days = int(d.get("days_elapsed", requested_increment))
        raw_summary = d.get("summary")
        summary = str(raw_summary).strip() if raw_summary is not None else None
    except (ValueError, TypeError, AttributeError, yaml.YAMLError):
        return _default(requested_increment)
    if days < 1:
        logger.warning("advance: days_elapsed %d < 1, clamping to 1", days)
        days = 1
    if days > requested_increment:
        logger.warning(
            "advance: days_elapsed %d > %d, clamping",
            days,
            requested_increment,
        )
        days = requested_increment
    return days, summary if summary else f"{days}{DEFAULT_MESSAGE}"


def read_current_day(kb: KnowledgeStore, timeline_id: str) -> int:
    """Read the current day counter from a timeline KB object.

    Raises :class:`ValidationError` if the object is missing or lacks
    a ``- Day: N`` line.
    """
    objs = kb.get_objects([timeline_id])
    obj = objs.get(timeline_id)
    if obj is None:
        raise ValidationError(
            f"timeline object '{timeline_id}' not found — "
            "advance requires a timeline KB object with '- Day: N'"
        )
    match = _DAY_COUNTER_RE.search(obj.text)
    if not match:
        raise ValidationError(
            f"timeline '{timeline_id}' has no '- Day: N' line — "
            "advance requires a day counter"
        )
    return int(match.group(2))


def update_timeline_day(
    kb: KnowledgeStore,
    timeline_id: str,
    days_elapsed: int,
    storage: Storage,
) -> None:
    """Increment the day counter in a timeline KB object."""
    objs = kb.get_objects([timeline_id])
    obj = objs.get(timeline_id)
    if obj is None:
        raise OperatorError(f"timeline object not found: {timeline_id}")
    match = _DAY_COUNTER_RE.search(obj.text)
    if not match:
        raise OperatorError(
            f"timeline {timeline_id} has no '- Day: N' line to increment"
        )
    current = int(match.group(2))
    updated = _DAY_COUNTER_RE.sub(
        f"{match.group(1)}{current + days_elapsed}", obj.text, count=1
    )
    local_kb = KnowledgeStore.for_project(
        storage.root, storage=storage  # type: ignore[arg-type]
    )
    local_kb.store_object(timeline_id, updated)


# ---------------------------------------------------------------------------
# Narrative slice: anchor finding
# ---------------------------------------------------------------------------


@dataclass
class AdvanceAnchorResult:
    """Result of searching for the previous completed advance."""
    anchor: SliceAnchor
    advance_id: str


def _rightmost_dfs(node: NarrativeNode) -> Iterator[NarrativeNode]:
    """Yield *node* and its descendants in reverse reading order (deepest-rightmost first)."""
    children = node.child_keys()
    for key in reversed(children):
        yield from _rightmost_dfs(node.child_node(key))
    yield node


def _walk_reading_order_backward(start: NarrativeNode) -> Iterator[NarrativeNode]:
    """Yield nodes in reverse reading order, starting just before *start*.

    Does **not** yield *start* itself.
    """
    node = start
    while node.key_path:
        parent = NarrativeNode(
            narrative_root=node.narrative_root,
            key_path=node.key_path[:-1],
        )
        try:
            siblings = parent.child_keys()
        except FileNotFoundError:
            node = parent
            continue
        try:
            my_idx = siblings.index(node.key_path[-1])
        except ValueError:
            node = parent
            continue

        # Previous siblings in reverse, depth-first (rightmost descendants first).
        for i in range(my_idx - 1, -1, -1):
            yield from _rightmost_dfs(parent.child_node(siblings[i]))

        # Then the parent itself.
        yield parent

        node = parent


def _check_node_for_advance_anchor(
    node: NarrativeNode,
    timeline_id: str,
    current_day: int,
) -> AdvanceAnchorResult | None:
    """Check *node* for a completed advance matching *timeline_id*.

    Scans segments in reverse (most recent first).  Returns the first valid
    anchor found, or ``None`` if no matching advance exists on this node.

    Raises :class:`OperatorError` if a matching-timeline advance is found but
    fails day-counter validation.
    """
    try:
        text = node.md_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    segments = parse_segments(text)

    for seg in reversed(segments):
        ann = seg.annotation
        if ann is None or ann.operator != "advance" or seg.close is None:
            continue
        # Must have timeline param to be a valid anchor.
        ann_timeline = ann.params.get("timeline")
        if ann_timeline is None:
            continue
        if ann_timeline != timeline_id:
            continue

        # Found a matching-timeline completed advance.  Validate.
        advance_id = ann.id
        if advance_id is None:
            continue

        start_day = int(ann.params.get("current_day", 1))
        increment = int(ann.params.get("increment", 1))

        # Read the sub-node to get actual days_elapsed.
        child = node.child_node(advance_id)
        if child.exists():
            child_text = child.md_path().read_text(encoding="utf-8")
            days_elapsed, _summary = parse_advance_result(child_text, increment)
        else:
            days_elapsed = increment

        if start_day + days_elapsed != current_day:
            raise ValidationError(
                f"advance anchor validation failed for {advance_id}: "
                f"start_day ({start_day}) + days_elapsed ({days_elapsed}) = "
                f"{start_day + days_elapsed}, but current timeline day is "
                f"{current_day}. The timeline may have been edited manually."
            )

        return AdvanceAnchorResult(
            anchor=SliceAnchor(node=node, line_end=seg.close.line_end + 1),
            advance_id=advance_id,
        )

    return None


def find_advance_anchor(
    cursor: NarrativeNode,
    timeline_id: str,
    current_day: int,
) -> AdvanceAnchorResult | None:
    """Find the most recent completed advance for *timeline_id*.

    Searches backward in narrative reading order from *cursor*.  Returns
    ``None`` if no prior advance exists (first advance for this timeline).

    Raises :class:`OperatorError` if a matching advance is found but the
    day-counter validation fails.
    """
    # Check the cursor node itself first.
    result = _check_node_for_advance_anchor(cursor, timeline_id, current_day)
    if result is not None:
        return result

    # Walk backward through the tree.
    for node in _walk_reading_order_backward(cursor):
        result = _check_node_for_advance_anchor(node, timeline_id, current_day)
        if result is not None:
            return result

    return None


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class AdvanceOperator(Operator):
    name: ClassVar[str] = "advance"
    requires_id: ClassVar[bool] = True
    limited_to_datasets: ClassVar[list[str]] = ["rpg"]
    use_command_tools: ClassVar[bool] = True

    @property
    def system_prompt(self) -> str:
        return PromptStore(self.project_root).get("advance.system")

    def build_instruction(self, params: dict[str, Any]) -> str:
        days = params.get("increment", 1)
        current_day = params.get("current_day", "?")
        luck_rolls: dict[str, tuple[int, int] | list[int]] = params.get(
            "luck_rolls", {}
        )
        if luck_rolls:
            rolls_text = "\n".join(
                f"  - {fid}: roll1={_roll_pair(r)[0]}, roll2={_roll_pair(r)[1]}"
                for fid, r in luck_rolls.items()
            )
        else:
            rolls_text = "  (no fronts tagged to this timeline)"
        return PromptStore(self.project_root).format(
            "advance.instruction_template",
            days=days,
            current_day=current_day,
            rolls_text=rolls_text,
        )

    @classmethod
    def check_requirements(cls, crawl_result: CrawlResult) -> None:
        pinned = set(crawl_result.pinned_ids)
        if not any(pid.startswith("timeline.") for pid in pinned):
            raise ValidationError(
                "advance requires at least one timeline.* to be pinned — "
                "add a timeline KB object with --pin or kb_pin front matter"
            )

    @classmethod
    def _find_active_session(
        cls, narrative: NarrativeNode
    ) -> tuple[NarrativeNode | None, str | None]:
        cursor = narrative.find_cursor()
        if not cursor.key_path:
            return None, None
        parent = NarrativeNode(
            narrative_root=cursor.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        try:
            parent_text = parent.md_path().read_text(encoding="utf-8")
        except FileNotFoundError:
            return None, None
        open_ann = find_unclosed_cursor_annotation(parent_text)
        if open_ann is not None and open_ann.operator == cls.name:
            return cursor, open_ann.id
        return None, None

    @classmethod
    def _unclosed_advance_on_node(cls, node: NarrativeNode) -> bool:
        text = node.md_path().read_text(encoding="utf-8")
        ann = find_unclosed_cursor_annotation(text)
        return ann is not None and ann.operator == cls.name

    @classmethod
    async def _run_generation(
        cls,
        *,
        op: AdvanceOperator,
        child_node: NarrativeNode,
        ann_params: dict[str, Any],
        existing_ann: ParsedAnnotation | None,
        session: ProjectSession,
        llm_id: str | None,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
        feedback_messages: list[dict[str, str]] | None = None,
        pre_retry_snapshot: str | None = None,
        workflow: Any | None = None,
    ) -> None:
        # Narrative slice: use spine from previous advance instead of full
        # ancestor crawl.  KB pin resolution is always full-chain.
        slice_anchor: SliceAnchor | None = None
        timeline_id = ann_params.get("timeline")
        if isinstance(timeline_id, str):
            parent_node = NarrativeNode(
                narrative_root=child_node.narrative_root,
                key_path=child_node.key_path[:-1],
            )
            anchor_result = find_advance_anchor(
                parent_node, timeline_id, int(ann_params.get("current_day", 1))
            )
            if anchor_result is not None:
                slice_anchor = anchor_result.anchor

        crawl_result = crawl(
            cls.crawl_spec(
                child_node,
                ann_params,
                session=session,
                narrative=op.narrative_root,
                anchor=slice_anchor,
                storage=op.storage,
            )
        )
        ctx, resolved = op._modality_context(
            crawl_result,
            ann_params,
            session=session,
            narrative=op.narrative_root,
        )
        messages = op.build_messages(
            crawl_result,
            ann_params,
            session=session,
            narrative=op.narrative_root,
            resolved_modalities=resolved,
        )
        if feedback_messages:
            messages.extend(feedback_messages)

        def _restore_pre_retry() -> None:
            if pre_retry_snapshot is not None and existing_ann is not None:
                op.storage.write_file(child_node.md_path(), pre_retry_snapshot)

        tools_payload, command_handlers = cls.merge_command_tools_for_generation(
            resolved, ctx, session.project_root, ann_params
        )

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
                    enable_thinking=True,
                    reasoning=reasoning,
                    cancel_event=cancel_event,
                    on_token=on_token,
                    operator_name=cls.name,
                ),
            )
        except LLMError as e:
            _restore_pre_retry()
            raise OperatorError(f"LLM error: {e}") from e

        if artifacts.interrupted:
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
            op.write_append(child_node, existing_ann, artifacts=artifacts)
        else:
            inline_tag = op.build_open_tag(None, ann_params)
            op.write_start(child_node, inline_tag, artifacts=artifacts)

    @classmethod
    async def _run_advance_end(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
    ) -> KbExtractResult:
        cursor = narrative.find_cursor()
        if not cursor.key_path:
            raise ValidationError(
                "no open advance to close (cursor must be in the advance sub-node)"
            )
        session_id = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=cursor.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        parent_text = parent.md_path().read_text(encoding="utf-8")
        open_ann = find_unclosed_cursor_annotation(parent_text)
        if (
            open_ann is None
            or open_ann.operator != cls.name
            or open_ann.id != session_id
        ):
            raise ValidationError(
                f"parent does not have unclosed [advance:{session_id}]: # — "
                "cursor must be in the advance sub-node"
            )

        child_text = cursor.md_path().read_text(encoding="utf-8")
        probe_op = cls(session.new_storage(), narrative)
        inline_ann = probe_op.find_open_annotation(cursor)
        if inline_ann is None or inline_ann.id is not None:
            raise ValidationError(
                "advance sub-node has no inline [advance …]: # block to read params from"
            )
        requested_increment = int(inline_ann.params.get("increment", 1))

        child_crawl = crawl(
            cls.crawl_spec(
                cursor,
                dict(inline_ann.params),
                session=session,
                narrative=narrative,
            )
        )
        cls.check_requirements(child_crawl)
        timeline_ids = [
            p for p in child_crawl.pinned_ids if p.startswith("timeline.")
        ]
        if not timeline_ids:
            raise ValidationError(
                "advance --end requires a pinned timeline.* on the sub-node"
            )

        rel_path = str(parent.md_path().relative_to(session.git_root))
        owner = cls.owner_id(session_id, rel_path)
        storage = session.new_storage(owner=owner)
        if storage.has_pending() and storage.detect_pending_owner() == owner:
            storage.stage_all()
        op = cls(storage, narrative)

        days_elapsed, summary = parse_advance_result(
            child_text, requested_increment
        )
        result = kb_extract_from_text(child_text, session.project_root, storage)
        for err in result.errors:
            logger.warning("advance end: %s", err)

        update_timeline_day(
            session.kb, timeline_ids[0], days_elapsed, storage
        )

        current_day = int(inline_ann.params.get("current_day", 0))
        try:
            summary_block = format_summary_block(session_id, summary)
        except SummaryTitleError:
            fallback_title = f"Advance (Day {current_day})"
            summary_block = format_summary_block(
                session_id, f"{fallback_title}\n\n{summary}"
            )
        op.close_subnode(parent, session_id, summary_block)
        return result

    @classmethod
    async def _run_advance_retry(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        reasoning: str | None = None,
        feedback: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
    ) -> KbExtractResult:
        cursor = narrative.find_cursor()
        _session_node, session_id = cls._find_active_session(narrative)
        if session_id is None or cursor.key_path[-1] != session_id:
            raise ValidationError(
                "advance --retry requires the cursor in the active advance sub-node"
            )

        probe_storage = session.new_storage()
        has_pending = probe_storage.has_pending()
        pending_owner = probe_storage.detect_pending_owner() if has_pending else None

        child_rel_path = str(cursor.md_path().relative_to(session.git_root))
        probe_op = cls(probe_storage, narrative)
        existing_ann = probe_op.find_open_annotation(cursor)
        if existing_ann is None:
            raise ValidationError("no advance annotation found to retry")

        ann_owner = cls._owner_for_ann(existing_ann, child_rel_path)
        is_owner = (pending_owner == ann_owner) if has_pending else False
        if not is_owner:
            raise ValidationError("no pending advance transaction to retry")

        # Capture previous content before discarding (for feedback mode).
        previous_content: str | None = None
        if feedback:
            previous_content = extract_annotation_content(cursor.md_path(), existing_ann)

        storage = session.new_storage(owner=ann_owner)
        op = cls(storage, narrative)

        new_params: dict[str, Any] = dict(existing_ann.params)
        if pins:
            pin_node(cursor, pins, storage)
        if unpins:
            unpin_node(cursor, unpins, storage)

        pre_retry_snapshot = cursor.md_path().read_text(encoding="utf-8")
        op.write_discard(cursor, existing_ann, updated_params=new_params)
        fresh_ann = op.find_open_annotation(cursor)
        if fresh_ann is None:
            op.storage.write_file(cursor.md_path(), pre_retry_snapshot)
            raise OperatorError("lost annotation after discard")

        if on_stream_target is not None:
            await on_stream_target(str(cursor.to_address()))

        feedback_messages: list[dict[str, str]] | None = None
        if feedback and previous_content:
            feedback_messages = build_feedback_messages(previous_content, feedback, session.project_root)

        eff_reasoning: str | None = new_params.get("reasoning")
        if reasoning:
            new_params["reasoning"] = reasoning
            eff_reasoning = reasoning
        await cls._run_generation(
            op=op,
            child_node=cursor,
            ann_params=new_params,
            existing_ann=fresh_ann,
            session=session,
            llm_id=llm_id,
            reasoning=eff_reasoning,
            on_token=on_token,
            cancel_event=cancel_event,
            feedback_messages=feedback_messages,
            pre_retry_snapshot=pre_retry_snapshot,
        )
        return KbExtractResult()

    @classmethod
    async def _run_advance_fresh(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        increment: int,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        reasoning: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
    ) -> KbExtractResult:
        cursor = narrative.find_cursor()
        if cls._unclosed_advance_on_node(cursor):
            raise ValidationError(
                "an advance session is already open — open the advance sub-node "
                "and run `lens advance --end`, or discard changes, before starting another"
            )

        pre_crawl = crawl(
            cls.crawl_spec(
                cursor,
                {},
                session=session,
                narrative=narrative,
                extra_pins=pins,
                extra_unpins=unpins,
            )
        )
        cls.check_requirements(pre_crawl)

        timeline_ids = [p for p in pre_crawl.pinned_ids if p.startswith("timeline.")]
        current_day = read_current_day(session.kb, timeline_ids[0])
        front_ids = _front_ids_from_pins(pre_crawl.pinned_ids)
        luck_rolls = generate_luck_rolls(front_ids)
        ann_params: dict[str, Any] = {
            "increment": increment,
            "current_day": current_day,
            "timeline": timeline_ids[0],
            "luck_rolls": luck_rolls,
        }

        advance_id = generate_advance_id(cursor, current_day)
        rel_path = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(advance_id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)

        child_node = op.create_subnode(cursor, advance_id, params=ann_params)

        all_pins = list(pins)
        if DESIGN_MODULE_PIN not in pre_crawl.pinned_ids:
            all_pins.append(DESIGN_MODULE_PIN)
        if all_pins:
            pin_node(child_node, all_pins, storage)
        if unpins:
            unpin_node(child_node, unpins, storage)

        storage.stage_all()

        if on_stream_target is not None:
            await on_stream_target(str(child_node.to_address()))

        child_rel_path = str(child_node.md_path().relative_to(session.git_root))
        ann_line = cls.ann_line_for_append(
            child_node.md_path().read_text(encoding="utf-8")
        )
        inline_owner = cls.owner_id(None, child_rel_path, line=ann_line)
        inline_storage = session.new_storage(owner=inline_owner)
        inline_op = cls(inline_storage, narrative)

        if reasoning:
            ann_params["reasoning"] = reasoning
        await cls._run_generation(
            op=inline_op,
            child_node=child_node,
            ann_params=ann_params,
            existing_ann=None,
            session=session,
            llm_id=llm_id,
            reasoning=reasoning,
            on_token=on_token,
            cancel_event=cancel_event,
        )
        return KbExtractResult()

    @classmethod
    async def run_advance(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        increment: int = 1,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None = None,
        reasoning: str | None = None,
        retry: bool = False,
        feedback: str | None = None,
        end: bool = False,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_stream_target: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> KbExtractResult:
        """Run advance: fresh generation, retry, or end (apply KB + close)."""
        if end:
            return await cls._run_advance_end(
                session=session,
                narrative=narrative,
            )
        if increment < 1:
            raise ValidationError("advance increment must be >= 1")
        if retry:
            return await cls._run_advance_retry(
                session=session,
                narrative=narrative,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                reasoning=reasoning,
                feedback=feedback,
                on_token=on_token,
                on_stream_target=on_stream_target,
                cancel_event=cancel_event,
            )
        active, _ = cls._find_active_session(narrative)
        if active is not None:
            raise ValidationError(
                "an advance session is in progress — use `lens advance --end` "
                "to apply changes or `lens advance --retry` to regenerate"
            )
        return await cls._run_advance_fresh(
            session=session,
            narrative=narrative,
            increment=increment,
            pins=pins,
            unpins=unpins,
            llm_id=llm_id,
            reasoning=reasoning,
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=cancel_event,
        )


def _roll_pair(r: tuple[int, int] | list[int]) -> tuple[int, int]:
    if isinstance(r, tuple):
        return int(r[0]), int(r[1])
    return int(r[0]), int(r[1])
