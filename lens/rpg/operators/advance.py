"""Advance operator: pass the time, update fronts, resolve consequences.

``lens advance [--days N]`` creates an ``advance-day-*`` sub-node, pins fronts
tagged to the pinned timeline (with ``+`` for expansion), and runs the LLM with
the ``design.front`` module. KB updates and the timeline day counter apply only
after ``lens advance --end`` (with the cursor in that sub-node). Use
``lens advance --retry`` to discard the last generated block and regenerate.

Dataset-gated: requires the ``rpg`` dataset.

Requirements: ``design.front`` and at least one ``timeline.*`` must be pinned.
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

from lens.core.annotations import ParsedAnnotation
from lens.core.command_tools import get_command_registry
from lens.core.commands.kb import KbExtractResult, kb_extract_from_text
from lens.core.context import CrawlResult, SliceAnchor, assemble_prompt, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import LLMError, generate_stream
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation, parse_segments
from lens.core.operator import Operator, OperatorError
from lens.core.pinning import pin as pin_node
from lens.core.pinning import unpin as unpin_node
from lens.core.project import ProjectSession
from lens.core.storage import Storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the campaign timeline manager. Your job is to evaluate what happens \
in the world when time passes by reading and updating fronts, which may include \
resolving clocks and timers, and determining if anything interrupts a proposed time jump.

Rerence the content of [DESIGN MODULE]: FRONT GROOMING. Follow its \
front grooming rules when updating or creating fronts. You are running the \
front design module in the context of time passing: you are in "advance mode".

HOW TO WORK:

1. Think through each front. Use the provided luck rolls to resolve any \
chance mechanics described in the front (e.g. "every N days there is a Y% \
chance that Z happens"). The first roll is the primary roll; the second is \
for tables or secondary checks. Do not use rolls unless a front asks.

2. Update fronts via "KB blocks". Preserve all existing content and only \
change what the passage of time affects — clocks, timers, phases, statuses. \
Use kb_get to inspect any front before modifying it.

Using this format, known as a "KB block" (fenced block with front-matter id field) to update a front:

```kb
---
id: front.key
---
Markdown content here; fully replaces any existing content!
```

Include as many blocks as needed, one per item, You can write any text around blocks to \
think, discuss, or explain; only the blocks have side-effects in the knowledge base, and \
only the last block for that id has effect, so you can change your mind and try again as you go.

3. At least ONE day has to pass, as this reprsent the day ALREADY ELAPSES in the fiction, \
therefore the first day increment CANNOT have ANY retroactive time effects or interrupt the narrative. \
It's likely that the narrative already covered a front effect (for example, the players battled and enemy in \
a front and now it's at the end of the day. It's therefore important that you account for all that has transpired \
in the front object. If something was missed that should have happened visible, let's just say it happens \
the next day. Trigger an interruption and stop advancing time (but still update all fronts for one day).

4. If the first day generates no interruption, and more than one day increment was requested, \
determine the actual days elapsed by evaluating the fronts and checking any INTERRUPTS the narrative \
(a random encounter triggers, urgent news reaches the PCs, etc.), only ONE \
front may interrupt. If this happens, then the timeline and all fronts can only advance by that much.
Report the actual days that passed before interruption (at least 1 and less than requested). \
Note that this is NOT common! Only interrupt if the front tells you to, or if it obiously makes sense, \
for example a visible event occurrs in the same location the narrative is currently at.

5. You can emit an ``advance`` fenced block if either there was an interruption, \
or if you want to describe anything interesting that happened that the player should \
know. If time was cut short by an interruption, you myst always include \
``days_elapsed`` with the actual days elapsed and a summary of what happened to \
interrupt the original amount!

```advance
days_elapsed: <N>   # only when interrupted — omit if full time passed
summary: |
  Three days pass as you hike through the countryside. The road grows quieter as autumn sets in.
```

If there is an interruption, the summary must describe the triggering current \
situation in more detail so the scene can be played out immediately after.
If a advance block is not emitted, the time will be incremented by the amount \
requested and the summary will be that that may days have passed. This is \
normal and usually the default outcome.

What NOT to do:
- Do not write extended narrative prose — keep the summary brief.
- Do not roll dice or make decisions for player characters.
- Do not update fronts that are unaffected by the time passage.
- Do not create fronts unless the front design module says it's appropriate.
"""

INSTRUCTION_TEMPLATE = """\
The player ends the day. Advance time by up to {days} day(s).
Current day counter: {current_day}.

Luck rolls for each front:
{rolls_text}

For each front: evaluate what changes given the time passed and the \
narrative so far. Update clocks, timers, and phases. Use the luck rolls to \
resolve chance mechanics as described in each front.

If any front INTERRUPTS the time jump (random encounter, urgent event \
reaching the PCs), only one front may interrupt. Report the actual days \
that passed before interruption.

Output:
1. Your reasoning about each front (use thinking)
2. ```kb blocks for any front updates
3. ```advance block with summary field (and days_elapsed only if interrupted)\
"""

DESIGN_MODULE_PIN = "design.front"
DEFAULT_MESSAGE = " day(s) have passed."

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADVANCE_BLOCK_RE = re.compile(r"```advance\s*\n(.*?)\n```", re.DOTALL)
_DAY_COUNTER_RE = re.compile(r"^(- Day:\s*)(\d+)", re.MULTILINE)


def generate_advance_id(parent: NarrativeNode) -> str:
    """Generate ``advance-day-{N}`` where N is a monotonic counter."""
    existing = set(parent.child_keys())
    n = 1
    while f"advance-day-{n}" in existing:
        n += 1
    return f"advance-day-{n}"


def discover_front_pins(
    kb: KnowledgeStore,
    pinned_ids: list[str],
) -> list[str]:
    """Find all ``front.*`` IDs tagged with a pinned ``timeline.*``, return with ``+``."""
    timeline_ids = [p for p in pinned_ids if p.startswith("timeline.")]
    front_ids: set[str] = set()
    for tid in timeline_ids:
        front_ids.update(kb.get_ids_with_tag(tid, type_filter="front"))
    return [f"{fid}+" for fid in sorted(front_ids)]


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
    """Read the current day counter from a timeline KB object."""
    objs = kb.get_objects([timeline_id])
    obj = objs.get(timeline_id)
    if obj is None:
        return 1
    match = _DAY_COUNTER_RE.search(obj.text)
    return int(match.group(2)) if match else 1


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
            raise OperatorError(
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
    excluded_operator_tools: ClassVar[frozenset[str]] = frozenset({"write"})

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

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
        return INSTRUCTION_TEMPLATE.format(
            days=days,
            current_day=current_day,
            rolls_text=rolls_text,
        )

    @classmethod
    def check_requirements(cls, crawl_result: CrawlResult) -> None:
        pinned = set(crawl_result.pinned_ids)
        if DESIGN_MODULE_PIN not in pinned:
            raise OperatorError(
                "advance requires design.front to be pinned — "
                "add it with --pin or kb_pin front matter"
            )
        if not any(pid.startswith("timeline.") for pid in pinned):
            raise OperatorError(
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

    @staticmethod
    def _write_inline_block(
        storage: Storage,
        child_node: NarrativeNode,
        ann_params: dict[str, Any],
        content: str,
        op: AdvanceOperator,
    ) -> None:
        inline_tag = op.build_open_tag(None, ann_params)
        close_tag = op.build_close_tag(None)
        child_md = child_node.md_path()
        existing = child_md.read_text(encoding="utf-8") if child_md.exists() else ""
        sep = "\n" if existing.endswith("\n") else "\n\n"
        storage.write_file(
            child_md,
            existing
            + sep
            + inline_tag
            + "\n\n"
            + content.rstrip()
            + "\n\n"
            + close_tag
            + "\n",
        )

    @classmethod
    async def _run_generation(
        cls,
        *,
        op: AdvanceOperator,
        storage: Storage,
        child_node: NarrativeNode,
        ann_params: dict[str, Any],
        existing_ann: ParsedAnnotation | None,
        session: ProjectSession,
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
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

        crawl_result = crawl(child_node, anchor=slice_anchor)
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
                    op.write_append(child_node, existing_ann, content)
                else:
                    cls._write_inline_block(
                        storage, child_node, ann_params, content, op
                    )
            return

        if not content.strip():
            raise OperatorError("no content generated")

        if existing_ann is not None:
            op.write_append(child_node, existing_ann, content)
        else:
            cls._write_inline_block(storage, child_node, ann_params, content, op)

    @classmethod
    async def _run_advance_end(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
    ) -> KbExtractResult:
        cursor = narrative.find_cursor()
        if not cursor.key_path:
            raise OperatorError(
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
            raise OperatorError(
                f"parent does not have unclosed [advance:{session_id}]: # — "
                "cursor must be in the advance sub-node"
            )

        child_text = cursor.md_path().read_text(encoding="utf-8")
        probe_op = cls(session.new_storage(), narrative)
        inline_ann = probe_op.find_open_annotation(cursor)
        if inline_ann is None or inline_ann.id is not None:
            raise OperatorError(
                "advance sub-node has no inline [advance …]: # block to read params from"
            )
        requested_increment = int(inline_ann.params.get("increment", 1))

        child_crawl = crawl(cursor)
        cls.check_requirements(child_crawl)
        timeline_ids = [
            p for p in child_crawl.pinned_ids if p.startswith("timeline.")
        ]
        if not timeline_ids:
            raise OperatorError(
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

        op.append_to_node(parent, summary + "\n\n")
        op.append_to_node(parent, op.build_close_tag(session_id) + "\n")
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
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
    ) -> KbExtractResult:
        cursor = narrative.find_cursor()
        _session_node, session_id = cls._find_active_session(narrative)
        if session_id is None or cursor.key_path[-1] != session_id:
            raise OperatorError(
                "advance --retry requires the cursor in the active advance sub-node"
            )

        probe_storage = session.new_storage()
        has_pending = probe_storage.has_pending()
        pending_owner = probe_storage.detect_pending_owner() if has_pending else None

        child_rel_path = str(cursor.md_path().relative_to(session.git_root))
        probe_op = cls(probe_storage, narrative)
        existing_ann = probe_op.find_open_annotation(cursor)
        if existing_ann is None:
            raise OperatorError("no advance annotation found to retry")

        ann_owner = cls._owner_for_ann(existing_ann, child_rel_path)
        is_owner = (pending_owner == ann_owner) if has_pending else False
        if not is_owner:
            raise OperatorError("no pending advance transaction to retry")

        storage = session.new_storage(owner=ann_owner)
        op = cls(storage, narrative)

        new_params: dict[str, Any] = dict(existing_ann.params)
        if pins:
            pin_node(cursor, pins, storage)
        if unpins:
            unpin_node(cursor, unpins, storage)

        op.write_discard(cursor, existing_ann, updated_params=new_params)
        fresh_ann = op.find_open_annotation(cursor)
        if fresh_ann is None:
            raise OperatorError("lost annotation after discard")

        if on_stream_target is not None:
            await on_stream_target(str(cursor.to_address()))

        await cls._run_generation(
            op=op,
            storage=storage,
            child_node=cursor,
            ann_params=new_params,
            existing_ann=fresh_ann,
            session=session,
            llm_id=llm_id,
            on_token=on_token,
            cancel_event=cancel_event,
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
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
    ) -> KbExtractResult:
        cursor = narrative.find_cursor()
        if cls._unclosed_advance_on_node(cursor):
            raise OperatorError(
                "an advance session is already open — open the advance sub-node "
                "and run `lens advance --end`, or discard changes, before starting another"
            )

        pre_crawl = crawl(cursor, extra_pins=pins, extra_unpins=unpins)
        cls.check_requirements(pre_crawl)

        front_pins = discover_front_pins(session.kb, pre_crawl.pinned_ids)
        timeline_ids = [p for p in pre_crawl.pinned_ids if p.startswith("timeline.")]
        current_day = read_current_day(session.kb, timeline_ids[0])
        raw_front_ids = [f.rstrip("+") for f in front_pins]
        luck_rolls = generate_luck_rolls(raw_front_ids)
        ann_params: dict[str, Any] = {
            "steps": 1,
            "increment": increment,
            "current_day": current_day,
            "timeline": timeline_ids[0],
            "luck_rolls": luck_rolls,
        }

        advance_id = generate_advance_id(cursor)
        rel_path = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(advance_id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)

        child_node = op.create_subnode(cursor, advance_id, params=ann_params)

        all_pins = list(pins)
        if DESIGN_MODULE_PIN not in pre_crawl.pinned_ids:
            all_pins.append(DESIGN_MODULE_PIN)
        all_pins.extend(front_pins)
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

        await cls._run_generation(
            op=inline_op,
            storage=inline_storage,
            child_node=child_node,
            ann_params=ann_params,
            existing_ann=None,
            session=session,
            llm_id=llm_id,
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
        retry: bool = False,
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
            raise OperatorError("advance increment must be >= 1")
        if retry:
            return await cls._run_advance_retry(
                session=session,
                narrative=narrative,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                on_token=on_token,
                on_stream_target=on_stream_target,
                cancel_event=cancel_event,
            )
        active, _ = cls._find_active_session(narrative)
        if active is not None:
            raise OperatorError(
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
            on_token=on_token,
            on_stream_target=on_stream_target,
            cancel_event=cancel_event,
        )


def _roll_pair(r: tuple[int, int] | list[int]) -> tuple[int, int]:
    if isinstance(r, tuple):
        return int(r[0]), int(r[1])
    return int(r[0]), int(r[1])
