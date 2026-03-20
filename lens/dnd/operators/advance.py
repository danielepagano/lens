"""Advance operator: pass the time, update fronts, resolve consequences.

``lens advance [--days N]`` marks that the day(s) have ended. It creates a
sub-node, pins all fronts tagged to the pinned timeline (with ``+`` for
expansion), runs the LLM with the ``design.front`` module to evaluate and
update fronts, then closes the sub-node with a narrative summary.

Dataset-gated: requires ``dnd`` (or another RPG dataset).

Requirements: ``design.front`` and at least one ``timeline.*`` must be pinned.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

import yaml

from lens.core.command_tools import get_command_registry
from lens.core.commands.kb import KbExtractResult, kb_extract_from_text
from lens.core.context import CrawlResult, assemble_prompt, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import LLMError, generate_stream
from lens.core.narrative import NarrativeNode
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
in the world when time passes — updating fronts, resolving clocks and timers, \
and determining if anything interrupts the proposed time jump.

The DESIGN MODULE for fronts (design.front) is in your context — follow its \
front grooming rules when updating or creating fronts. You are running the \
front design module in the context of time passing.

HOW TO WORK:

1. Think through each front. Use the provided luck rolls to resolve any \
chance mechanics described in the front (e.g. "every N days there is a Y% \
chance that Z happens"). The first roll is the primary roll; the second is \
for tables or secondary checks.

2. Update fronts via ```kb blocks. Preserve all existing content and only \
change what the passage of time affects — clocks, timers, phases, statuses. \
Use kb_get to inspect any front before modifying it.

3. Determine the actual days elapsed. If a front INTERRUPTS the time jump \
(a random encounter triggers, urgent news reaches the PCs, etc.), only ONE \
front may interrupt. Report the actual days that passed before interruption.

4. Report your result in a fenced advance block:

```advance
days_elapsed: <N>
```

Where N is the actual number of days that passed (may be less than requested \
if interrupted). If no interruption, N equals the requested increment.

5. Write a brief narrative summary (1-3 sentences, GM voice) of time passing. \
This is what the player sees — describe weather, travel progress, rumours \
heard, or simply "an uneventful night."

6. If a front interrupted: after the summary, describe the triggering event \
so the scene can be played out.

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
2. ```kb blocks for any front updates (including timeline day counter update)
3. ```advance block with days_elapsed: N
4. A brief narrative summary of time passing (1-3 sentences, GM voice)
5. If interrupted: describe what triggers the scene\
"""

DESIGN_MODULE_PIN = "design.front"

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
        ids = kb.get_ids_with_tag(tid)
        front_ids.update(fid for fid in ids if fid.startswith("front."))
    return [f"{fid}+" for fid in sorted(front_ids)]


def generate_luck_rolls(front_ids: list[str]) -> dict[str, tuple[int, int]]:
    """Two random 1-100 rolls per front for chance mechanics."""
    return {fid: (random.randint(1, 100), random.randint(1, 100)) for fid in front_ids}


def parse_advance_result(content: str, requested_increment: int) -> int:
    """Parse the ``advance`` fenced block for ``days_elapsed``.

    Returns the validated day count, clamped to [1, requested_increment].
    If no block is found, returns the full requested increment.
    """
    match = _ADVANCE_BLOCK_RE.search(content)
    if not match:
        return requested_increment
    try:
        data = yaml.safe_load(match.group(1))
        days = int(data.get("days_elapsed", requested_increment))
    except (ValueError, TypeError, AttributeError, yaml.YAMLError):
        return requested_increment
    if days < 1:
        logger.warning("advance: days_elapsed %d < 1, clamping to 1", days)
        return 1
    if days > requested_increment:
        logger.warning(
            "advance: days_elapsed %d > %d, clamping",
            days,
            requested_increment,
        )
        return requested_increment
    return days


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
        storage._git_root, storage=storage  # type: ignore[arg-type]
    )
    local_kb.store_object(timeline_id, updated)


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class AdvanceOperator(Operator):
    name: ClassVar[str] = "advance"
    requires_id: ClassVar[bool] = True
    limited_to_datasets: ClassVar[list[str]] = ["dnd"]
    use_command_tools: ClassVar[bool] = True
    excluded_operator_tools: ClassVar[frozenset[str]] = frozenset({"write"})

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        days = params.get("increment", 1)
        current_day = params.get("current_day", "?")
        luck_rolls: dict[str, tuple[int, int]] = params.get("luck_rolls", {})
        if luck_rolls:
            rolls_text = "\n".join(
                f"  - {fid}: roll1={r[0]}, roll2={r[1]}"
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

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

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
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_stream_target: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> KbExtractResult:
        """Run the advance operator.

        Creates a sub-node, discovers fronts, calls LLM, extracts KB updates,
        updates the timeline, and closes.

        Returns :class:`~lens.core.commands.kb.KbExtractResult`.
        """
        if increment < 1:
            raise OperatorError("advance increment must be >= 1")

        cursor = narrative.find_cursor()
        advance_id = generate_advance_id(cursor)

        rel_path = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(advance_id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)

        # 1. Create sub-node
        child_node = op.create_subnode(cursor, advance_id)

        # 2. Pre-crawl the cursor to find pinned timelines
        pre_crawl = crawl(cursor, extra_pins=pins, extra_unpins=unpins)
        cls.check_requirements(pre_crawl)

        # 3. Discover fronts tagged to pinned timelines, pin with +
        front_pins = discover_front_pins(session.kb, pre_crawl.pinned_ids)

        # 4. Pin design.front + front pins to sub-node front matter
        all_pins = list(pins)
        if DESIGN_MODULE_PIN not in [
            p for p in pre_crawl.pinned_ids if p == DESIGN_MODULE_PIN
        ]:
            all_pins.append(DESIGN_MODULE_PIN)
        all_pins.extend(front_pins)
        if all_pins:
            pin_node(child_node, all_pins, storage)
        if unpins:
            unpin_node(child_node, unpins, storage)

        # 5. Stage sub-node setup
        storage.stage_all()

        if on_stream_target is not None:
            await on_stream_target(str(child_node.to_address()))

        # 6. Read current day and generate luck rolls
        timeline_ids = [
            p for p in pre_crawl.pinned_ids if p.startswith("timeline.")
        ]
        current_day = read_current_day(session.kb, timeline_ids[0])
        raw_front_ids = [
            f.rstrip("+") for f in front_pins
        ]
        luck_rolls = generate_luck_rolls(raw_front_ids)

        # 7. Build annotation params
        ann_params: dict[str, Any] = {
            "steps": 1,
            "increment": increment,
            "current_day": current_day,
            "luck_rolls": luck_rolls,
        }

        # 8. Crawl the sub-node (fronts expanded via + pins)
        child_crawl = crawl(child_node)

        # 9. Build messages
        instruction = op.build_instruction(ann_params)
        messages = assemble_prompt(
            child_crawl,
            system_prompt=op.system_prompt,
            instruction=instruction,
        )

        # 10. Add command tools (kb_get, kb_with_tag)
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

        # 11. Generate with thinking mode
        child_rel_path = str(child_node.md_path().relative_to(session.git_root))
        ann_line = cls.ann_line_for_append(
            child_node.md_path().read_text(encoding="utf-8")
        )
        inline_owner = cls.owner_id(None, child_rel_path, line=ann_line)
        inline_storage = session.new_storage(owner=inline_owner)
        inline_op = cls(inline_storage, narrative)

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

        # Write content to sub-node
        if content.strip():
            inline_tag = inline_op.build_open_tag(None, ann_params)
            close_tag = inline_op.build_close_tag(None)
            child_md = child_node.md_path()
            existing = child_md.read_text(encoding="utf-8") if child_md.exists() else ""
            sep = "\n" if existing.endswith("\n") else "\n\n"
            inline_storage.write_file(
                child_md,
                existing + sep + inline_tag + "\n\n" + content.rstrip() + "\n\n" + close_tag + "\n",
            )

        if interrupted:
            return KbExtractResult()

        if not content.strip():
            raise OperatorError("no content generated")

        # 12. Parse advance result
        days_elapsed = parse_advance_result(content, increment)

        # 13. Extract KB updates from output
        result = kb_extract_from_text(content, session.project_root, inline_storage)
        for err in result.errors:
            logger.warning("advance: %s", err)

        # 14. Update timeline day counter
        update_timeline_day(session.kb, timeline_ids[0], days_elapsed, inline_storage)

        # 15. Close the advance sub-node on the parent
        inline_op.append_to_node(cursor, inline_op.build_close_tag(advance_id) + "\n")

        return result
