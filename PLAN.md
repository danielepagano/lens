# Plan: `advance` Operator

## Overview

The `advance` operator is a D&D-dataset-gated operator that marks time passing. It updates the day counter on a pinned `timeline.*` KB object, discovers all fronts tagged to that timeline, evaluates them with the LLM (using the `design.front` module), and optionally chains to `play` if a front interrupts.

Like `design`, it creates a **sub-node** for each invocation. Like `play`, it's **dataset-gated** (`limited_to_datasets = ['dnd']`).

---

## Files to Create

| File | Purpose |
|------|---------|
| `datasets/dnd/knowledge/timeline/_template.md` | Timeline KB template |
| `lens/dnd/operators/advance.py` | Core operator (in dnd package, dataset-gated) |
| `lens/cli/operators/advance.py` | CLI adapter |
| `lens/dnd/operators/test_advance.py` | Unit tests |

## Files to Modify

| File | Change |
|------|--------|
| `lens/server/routes/operators.py` | Add `AdvanceBody` + `/operator/advance` endpoint |
| `lens/server/ui/src/services/api.ts` | Add `AdvanceParams` + `runAdvance()` |
| `lens/server/ui/src/commands/operators.ts` | Add `advance` command definition + handler branch |

---

## Step 1: Timeline KB Template

Create `datasets/dnd/knowledge/timeline/_template.md`:

```markdown
<!-- A Timeline tracks the passage of in-world days for a narrative arc. Usage: pin to narrative, advance with `lens advance`. -->
<!-- TAG POLICY: a timeline does not need tags; fronts tag themselves TO their timeline (e.g. tag: timeline.epic). -->

Name: (how we reference this timeline, e.g. "The Grim Hollow Chronicle")

- Started: (reference date or description for the player, e.g. "1st of Deepwinter, 1492 DR")
- Day: 1

<!-- The day counter is managed by the advance operator. Do not edit manually. -->
```

## Step 2: Core Operator (`lens/dnd/operators/advance.py`)

### Class structure

```python
class AdvanceOperator(Operator):
    name = "advance"
    requires_id = True        # sub-node, like design
    limited_to_datasets = ['dnd']
    use_command_tools = True   # kb_get, kb_with_tag for front inspection
    excluded_operator_tools = frozenset({"write"})
```

### ID generation

```python
def generate_advance_id(parent: NarrativeNode) -> str:
    """Generate advance-day-{N} where N is a monotonic counter."""
    existing = set(parent.child_keys())
    n = 1
    while f"advance-day-{n}" in existing:
        n += 1
    base = f"advance-day-{n}"
    # Verify no collision (should never happen with monotonic counter)
    if base in existing:
        raise OperatorError(f"advance ID collision: {base} already exists")
    return base
```

Wait — the counter always increments past existing keys, so by construction `base` can never be in `existing` after the while loop. Instead, we simply error if there's an unexpected gap or corruption:

```python
def generate_advance_id(parent: NarrativeNode) -> str:
    existing = set(parent.child_keys())
    n = 1
    while f"advance-day-{n}" in existing:
        n += 1
    return f"advance-day-{n}"
```

No collision handling needed — the while loop guarantees uniqueness. If something external creates a conflicting key between the check and use, Storage's transaction semantics will catch it.

### Requirements check

```python
@classmethod
def check_requirements(cls, crawl_result):
    pinned = set(crawl_result.pinned_ids)
    # Need design.front module
    if "design.front" not in pinned:
        raise OperatorError("advance requires design.front to be pinned")
    # Need at least one timeline.*
    if not any(pid.startswith("timeline.") for pid in pinned):
        raise OperatorError("advance requires at least one timeline.* to be pinned")
```

### Front discovery

The operator discovers fronts tagged to the pinned timeline(s) and adds them as pins **with `+`** to the sub-node front matter. The `+` suffix means when `crawl()` processes these pins (step 7 in normal crawl flow), it automatically expands to linked objects. The operator does NOT do expansion itself.

```python
def _discover_front_pins(session, crawl_result):
    """Find all front.* IDs tagged with the pinned timeline(s), return as pin list with +."""
    timeline_ids = [p for p in crawl_result.pinned_ids if p.startswith("timeline.")]
    front_ids = set()
    for tid in timeline_ids:
        # Find fronts tagged with this timeline
        ids = session.kb.get_ids_with_tag(tid)
        front_ids.update(fid for fid in ids if fid.startswith("front."))
    # Pin with + for expansion (crawl handles the expand)
    return [f"{fid}+" for fid in sorted(front_ids)]
```

### Luck rolls

Generate two random numbers (1-100) per front, passed to the AI in the prompt:

```python
import random
def _generate_luck_rolls(front_ids):
    return {fid: (random.randint(1, 100), random.randint(1, 100)) for fid in front_ids}
```

### Day increment collection via fenced `advance` block

After LLM generation completes, parse the output for a fenced block:

````
```advance
days_elapsed: 3
```
````

**Validation rules:**
- `days_elapsed` must be an integer >= 1
- `days_elapsed` must be <= the requested increment
- If no `advance` block is found, auto-increment by the full requested amount
- If validation fails (out of range), clamp to [1, increment] and log a warning

```python
import re, yaml

def _parse_advance_result(content: str, requested_increment: int) -> int:
    pattern = r'```advance\s*\n(.*?)\n```'
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return requested_increment  # default: full increment
    try:
        data = yaml.safe_load(match.group(1))
        days = int(data.get("days_elapsed", requested_increment))
    except (ValueError, TypeError, AttributeError):
        return requested_increment
    # Validate range
    if days < 1:
        logger.warning("advance: days_elapsed %d < 1, clamping to 1", days)
        return 1
    if days > requested_increment:
        logger.warning("advance: days_elapsed %d > %d, clamping", days, requested_increment)
        return requested_increment
    return days
```

### Timeline day counter update

After determining actual `days_elapsed`, update the timeline KB object:

```python
def _update_timeline_day(session, timeline_id, days_elapsed, storage):
    """Increment the day counter in the timeline KB object."""
    content = session.kb.get(timeline_id)
    # Parse "- Day: N" and increment
    updated = re.sub(
        r'^(- Day:\s*)(\d+)',
        lambda m: f"{m.group(1)}{int(m.group(2)) + days_elapsed}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    session.kb.put(timeline_id, updated, storage=storage)
```

### Main entry point: `run_advance`

Follows the design operator pattern — custom class method, not raw `run_inline`:

1. Find cursor, generate advance ID
2. Create sub-node (like design does)
3. Pin `design.front` + discovered front pins (with `+`) to sub-node front matter
4. Stage sub-node setup
5. Crawl the sub-node (fronts now expanded by crawl via `+` pins)
6. Build prompt with luck rolls, increment, system instructions
7. Generate with thinking mode + command tools
8. On completion:
   a. Parse `advance` fenced block → actual `days_elapsed`
   b. Run `kb_extract_from_text` on output (applies front updates)
   c. Update timeline day counter by `days_elapsed`
   d. Write narrative summary to the sub-node
   e. Close the advance annotation on the parent
   f. If AI signals interruption (days_elapsed < requested), chain to `play`

### System prompt

The system prompt instructs the AI to:
- Act as the campaign timeline manager
- Follow the `design.front` module for front grooming
- Evaluate each front for the time that passes
- Update clocks/timers using the provided luck rolls
- Determine if any front interrupts the proposed time jump
- Output `kb` blocks for front updates
- Output an `advance` block with `days_elapsed: N`
- Write a brief narrative summary of time passing

### Instruction builder

```python
def build_instruction(self, params):
    days = params.get("increment", 1)
    luck_rolls = params.get("luck_rolls", {})
    rolls_text = "\n".join(f"  - {fid}: roll1={r[0]}, roll2={r[1]}" for fid, r in luck_rolls.items())
    return (
        f"The player ends the day. Advance time by up to {days} day(s).\n\n"
        f"Luck rolls for each front:\n{rolls_text}\n\n"
        "For each front: evaluate what changes given the time passed and the narrative so far. "
        "Update clocks, timers, and phases. Use the luck rolls to resolve chance mechanics "
        "as described in each front.\n\n"
        "If any front INTERRUPTS the time jump (random encounter, urgent event reaching the PCs), "
        "only one front may interrupt. Report the actual days that passed before interruption.\n\n"
        "Output:\n"
        "1. Your reasoning about each front (thinking)\n"
        "2. ```kb blocks for any front updates\n"
        "3. ```advance block with days_elapsed: N (N = actual days passed, may be less than requested)\n"
        "4. A brief narrative summary of time passing (1-3 sentences, in GM voice)\n"
        "5. If interrupted: describe what triggers the interruption scene\n"
    )
```

## Step 3: CLI Adapter (`lens/cli/operators/advance.py`)

Follows the play pattern:

```python
@app.callback()
def advance(
    days: int = typer.Option(1, "--days", "-d", help="Days to advance (default: 1)"),
    pin: list[str] = pin_option("KB ID to pin"),
    unpin: list[str] = unpin_option(),
    llm: str | None = typer.Option(None, "--llm", "-l"),
    retry: bool = typer.Option(False, "--retry", "-r"),
) -> None:
    """Advance time, update fronts, resolve consequences."""
    # ... standard session/narrative setup ...
    asyncio.run(AdvanceOperator.run_advance(
        session=session, narrative=narrative,
        increment=days, pins=list(pin), unpins=list(unpin),
        llm_id=llm, retry=retry, on_token=_print_token,
    ))
```

## Step 4: Server Route

Add to `lens/server/routes/operators.py`:

```python
class AdvanceBody(BaseModel):
    days: int = 1
    pins: list[str] = []
    unpins: list[str] = []
    llm_id: str | None = None
    retry: bool = False

@router.post("/operator/advance")
async def operator_advance(
    body: AdvanceBody,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    from lens.dnd.operators.advance import AdvanceOperator
    # Same pattern as design: narrative, validate_pins, cursor, lock, queue, etc.
    # Uses on_stream_target for sub-node creation
    # Passes days as extra param
```

## Step 5: Frontend API + Command

### `api.ts`

```typescript
export interface AdvanceParams {
  days?: number
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  retry?: boolean
}

export const runAdvance = (
  params: AdvanceParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/advance', params, onEvent)
```

### `operators.ts`

Add to `commands` array:

```typescript
{
  trigger: 'advance',
  group: 'dnd',
  requiresDataset: 'dnd',
  positional: [],
  options: [
    { name: 'days', valueType: 'line', hint: 'days to advance (default: 1)' },
    { name: 'pin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to pin' },
    { name: 'unpin', valueType: 'kb-id', repeatable: true, hint: 'KB ID to unpin' },
    { name: 'llm', valueType: 'slug', slugSource: '[stats.available_llms]', hint: 'LLM to use' },
    { name: 'retry' },
  ],
}
```

Add handler branch:

```typescript
} else if (command === 'advance') {
  const days = ctx.args.options['days'] ? parseInt(ctx.args.options['days'] as string, 10) : undefined
  result = await runAdvance(
    { days, pins, unpins, llm_id: llmId, retry },
    handleEvent
  )
}
```

Visibility: same gating as play — requires `dnd` dataset. Additionally requires at least one `timeline.*` in effective pins.

## Step 6: Tests

Unit tests in `lens/dnd/operators/test_advance.py`:
- `test_generate_advance_id` — monotonic counter, no collision
- `test_discover_front_pins` — finds fronts tagged to timeline, returns with `+`
- `test_luck_rolls` — correct format, range 1-100
- `test_parse_advance_result` — parses fenced block, validates range, defaults
- `test_update_timeline_day` — increments day counter correctly
- `test_check_requirements` — errors without design.front, without timeline.*
- Integration: mock LLM, verify sub-node creation, KB extraction, timeline update

## Step 7: Run `poe check`

Verify lint + typecheck + unit tests + integration tests + e2e all pass.
