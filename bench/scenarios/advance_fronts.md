# Advance: front grooming and time passage

Tests whether the `advance` operator correctly evaluates fronts when time
passes — updating clocks and phases via `kb` blocks, applying luck rolls only
when a front's chance mechanic calls for them, and distinguishing a clean
multi-day pass (no interruption) from a genuine interruption (one front fires,
days cut short, summary explains the trigger). Uses the bundled `rpg` dataset
with two hand-written fronts and a timeline.

```config
datasets:
  - rpg
```

**Prompt keys exercised:** `advance.system`, `advance.instruction_template`

## Setup

Create a timeline, two fronts (one with a chance mechanic, one on a hard
schedule), tag them both to the timeline, then pin everything and establish
the narrative context.

**Implementation:** `bench/scenarios/advance_fronts_setup.sh` (canonical — edit
there first, then keep this prose aligned). From the **repo root** after
`setup_bench.py` prints the project path:

```bash
export PROJECT   # e.g. PROJECT=$(python bench/tools/setup_bench.py --profile grok --scenario bench/scenarios/advance_fronts.md)
bash bench/scenarios/advance_fronts_setup.sh
```

`lens` must be on `PATH` (e.g. Poetry venv). The script `cd`s to `$PROJECT`.

## Steps

### `single_day_clean`

Advance one day — tests whether the model reads both fronts, evaluates them
correctly for calendar **day 1→2**, emits `kb` blocks only for fronts that
actually change, and treats the pass as **uninterrupted** (no courier day-5
event). Prefer output that **omits** the fenced YAML block for the advance
result, or includes one with a `summary` only and **no** `days_elapsed` field
(or omits `days_elapsed` so the story is “quiet day”). If the model omits the
fence entirely, Lens
still advances the timeline by the **full requested increment** on `--end` (so
missing YAML does not mean zero days in the engine — score the prose/YAML on
its own merits). After a successful run, `timeline.vale` should show **`- Day: 2`**.

```bash
lens advance
lens advance --end
```

### `multi_day_interruption`

Runs **after** `single_day_clean`, so the timeline starts this step at **day 2**
(`- Day: 2` in `timeline.vale`). The CLI requests **up to** four days:
`lens advance --days 4` — without interruption that would reach calendar **day 6**
(2+4).

The courier front fires on **calendar day 5** (escape reaches the village). The
model should detect that **during** this batch and **not** apply the full four
days: the correct fenced `days_elapsed` is **3** (2→3→4→5). After
`lens advance --end`, `timeline.vale` should show **`- Day: 5`**, the courier
front should reflect the day-5 escape, and the `advance` block `summary`
should set the scene for what the PCs witness at that beat.

```bash
lens advance --days 4
lens advance --end
```

## Evaluation criteria

Score each step's output on a 1–5 scale:

1. **KB block correctness** — Only fronts that are actually affected by the elapsed days receive `kb` blocks; unaffected fronts are left untouched; updated content preserves all existing fields and changes only what time requires
2. **Chance mechanic handling** — Luck rolls are used only when a front specifies a chance mechanic; the model uses the provided rolls rather than inventing outcomes; roll interpretation matches the front's stated percentage
3. **Interruption detection** — In the multi-day step (from day 2): `advance` block has `days_elapsed: 3` (not 4); timeline ends at day 5 when the courier escape happens; single-day step either omits a fenced block or omits `days_elapsed` in YAML for a quiet pass
4. **Summary quality** — `advance` block `summary` field is brief, factual, and scene-setting; does not include extended GM narrative prose or PC decisions; interruption summary clearly names what changed
5. **Front integrity** — Updated `kb` blocks follow the front template structure (Problem, Stakes, Phases, etc.); the phase tracker reflects the new day accurately; no invented facts contradict the front's existing content

## Prompt iteration guidance

**Focus key:** `advance.system`

**Goal:** Precise, minimal front updates — only what time actually changes —
with correct interruption detection and clean `advance` block output.

**Anti-patterns to watch for:**

- **Spurious interruption** — Model invents an interruption on the clean single-day pass where no front triggers
- **Wrong days_elapsed** — Full **4** days applied when the courier should interrupt at **3** (still on `--days 4`); or timeline `- Day:` after `--end` not **5** when the scenario calls for the day-5 escape; or `days_elapsed` inconsistent with the stated courier beat
- **Over-writing fronts** — `kb` block rewrites the entire front with new invented content instead of targeted phase/clock updates
- **Ignored chance mechanic** — Model updates the blight front without referencing the provided luck rolls when day mod 2 == 0 applies
- **Narrative prose in summary** — `advance` block `summary` reads like a scene description rather than a brief factual handoff
- **Missing `kb` block** — A front that clearly advances (e.g. the blight crossing a phase boundary) receives no update
