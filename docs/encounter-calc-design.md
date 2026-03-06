# Encounter Calculator Design

## Overview

When the DM describes a narrative situation (e.g. zombies rising in a cemetery, bandits blocking the road, cultists trying to complete a ritual) the AI needs to find and assemble an appropriate set of monsters without loading every stat block into context. The AI uses `kb with-tag` to discover stat block candidates — submitting sets of CR tags (or no CR restriction), habitat filters, type filters, etc. — then calls a single LLM-callable tool:

**`balance_encounter`** — takes the AI's ranked candidate list plus party composition and produces up to three balanced encounter proposals using D&D 2024 XP budget math (internally; XP is never surfaced in output).

The AI uses `kb with-tag` to discover candidates, ranks them by narrative fit, then calls `balance_encounter` to get balanced monster lineups. The AI picks the best proposal and writes the encounter narratively. The tool is dataset-gated (`limited_to_datasets = ["dnd"]`) and registered via the standard `register_operator_tool` mechanism, making it available inside any operator when the `dnd` dataset is active during a planning operator such as `design`.

---

## User Flow

```
DM invokes designs and acounter in planning mode
  │
  ├─ AI assesses narrative situation and party composition
  │    (PCs are pinned; AI sees level:N tags from context — per pc/_template.md)
  │
  ├─ AI uses kb with-tag to discover candidates
  │    e.g. kb with-tag type:undead (cr:1 cr:2 cr:3 cr:1-4)
  │    or   kb with-tag (habitat:forest habitat:any)
  │    or   kb with-tag type:humanoid  (no CR restriction)
  │    → IDs with tags (CR/type/size/habitat) in with-tag's standard output
  │    AI may use kb list-tags --type stat --start-with cr: to learn tag values
  │
  ├─ AI decides:
  │    required  = specific stat blocks with fixed counts the scene demands
  │               (e.g. the vampire they're chasing, the noble + her guard unit)
  │    optional  = ranked list of fill-in candidates (no counts — tool decides)
  │
  ├─ AI calls balance_encounter(required, optional, difficulty, pcs, allies?)
  │    → if required is already over budget: warning + slim-down alternatives
  │    → otherwise: up to 3 fill proposals in count-table format
  │
  └─ AI picks winning proposal and creates encounter
```

---

## Tag Conventions

We need two tags for this to work:  
 - `cr:X` tag on `stat` (created by tooling reliably)
 - `level:X` tag on `pc` (maintained by user)

## CR Tag Encoding

Fractional CRs use the denominator as a hyphen-separated suffix:

| Stat block CR | Tag value | Float equivalent |
|---|---|---|
| 0 | `cr:0` | 0 |
| 1/8 | `cr:1-8` | 0.125 |
| 1/4 | `cr:1-4` | 0.25 |
| 1/2 | `cr:1-2` | 0.5 |
| 1 | `cr:1` | 1.0 |
| 2 | `cr:2` | 2.0 |
| … | … | … |
| 30 | `cr:30` | 30.0 |

Canonical CR-to-tag mapping:

```python
CR_TAG_ORDER: list[tuple[float, str]] = [
    (0,     "cr:0"),
    (0.125, "cr:1-8"),
    (0.25,  "cr:1-4"),
    (0.5,   "cr:1-2"),
    (1,     "cr:1"),
    (2,     "cr:2"),
    (3,     "cr:3"),
    # … integers 4–30
]
```

---

## D&D 2024 XP Budget Math

### Design choice: no monster-count multiplier

Monster XP is summed directly and compared against the party's XP budget for the requested difficulty. This is simpler to reason about and aligns with current rules.

### XP budget per character by level

The budget for an encounter = sum of each PC's budget at their level for the requested difficulty. Transcribed verbatim from the D&D 2024 DMG "XP Budget per Character" table.

| Level | Low | Moderate | High |
|---|---|---|---|
| 1 | 50 | 75 | 100 |
| 2 | 100 | 150 | 200 |
| 3 | 150 | 225 | 400 |
| 4 | 250 | 375 | 500 |
| 5 | 500 | 750 | 1,100 |
| 6 | 600 | 1,000 | 1,400 |
| 7 | 750 | 1,300 | 1,700 |
| 8 | 1,000 | 1,700 | 2,100 |
| 9 | 1,300 | 2,000 | 2,600 |
| 10 | 1,600 | 2,300 | 3,100 |
| 11 | 1,900 | 2,900 | 4,100 |
| 12 | 2,200 | 3,700 | 4,700 |
| 13 | 2,600 | 4,200 | 5,400 |
| 14 | 2,900 | 4,900 | 6,200 |
| 15 | 3,300 | 5,400 | 7,800 |
| 16 | 3,800 | 6,100 | 9,800 |
| 17 | 4,500 | 7,200 | 11,700 |
| 18 | 5,000 | 8,700 | 14,200 |
| 19 | 5,500 | 10,700 | 17,200 |
| 20 | 6,400 | 13,200 | 22,000 |

### Ally XP reduction

Allies reduce the effective challenge. Their XP is subtracted from the budget before selecting monsters:

```
adjusted_budget = Σ XP_BUDGET[pc_level][difficulty] − Σ CR_XP[ally_cr]
```

If `adjusted_budget ≤ 0` the encounter is trivially easy regardless of monster selection (allies alone outmatch the monsters). The tool reports this and proposes a token encounter.

### CR to XP table

Standard D&D XP values:

| CR | XP | CR | XP | CR | XP |
|---|---|---|---|---|---|
| 0 | 10 | 9 | 5,000 | 18 | 20,000 |
| 1/8 | 25 | 10 | 5,900 | 19 | 22,000 |
| 1/4 | 50 | 11 | 7,200 | 20 | 25,000 |
| 1/2 | 100 | 12 | 8,400 | 21 | 33,000 |
| 1 | 200 | 13 | 10,000 | 22 | 41,000 |
| 2 | 450 | 14 | 11,500 | 23 | 50,000 |
| 3 | 700 | 15 | 13,000 | 24 | 62,000 |
| 4 | 1,100 | 16 | 15,000 | 25 | 75,000 |
| 5 | 1,800 | 17 | 18,000 | 26 | 90,000 |
| 6 | 2,300 | | | 27 | 105,000 |
| 7 | 2,900 | | | 28 | 120,000 |
| 8 | 3,900 | | | 29 | 135,000 |
| | | | | 30 | 155,000 |

---

## Tool: `balance_encounter`

### Purpose

Given a fixed set of required monsters (stat block IDs with counts) and a ranked list of optional fill-in candidates, compute up to three encounter proposals that meet the requested difficulty. XP budget math is used internally; no XP figures are emitted. The required monsters are always included as-is; the tool decides counts only for the optional fill.

### JSON Schema (parameters)

```json
{
  "type": "object",
  "properties": {
    "required": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id":    {"type": "string", "description": "Stat block ID, e.g. 'stat.vampire'"},
          "count": {"type": "integer", "minimum": 1}
        },
        "required": ["id", "count"]
      },
      "description": "Monsters that must appear with specific counts. Can be empty if the AI has no fixed requirements."
    },
    "optional": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Ranked list of stat block IDs to fill out the encounter (most preferred first). The tool picks counts. Any number of candidates — weighted randomization ensures lower-ranked options still appear occasionally."
    },
    "difficulty": {
      "type": "string",
      "enum": ["low", "moderate", "high"],
      "description": "Target encounter difficulty."
    },
    "pcs": {
      "type": "array",
      "items": {"type": "integer", "minimum": 1, "maximum": 20},
      "description": "PC levels, one integer per PC. Example: [5, 5, 5, 5]."
    },
    "allies": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Optional ally CRs as fraction strings ('1/2', '2', etc.) that fight with the party and reduce the effective budget."
    }
  },
  "required": ["required", "optional", "difficulty", "pcs"]
}
```

### Implementation

#### Phase 1: Compute budget and committed XP

```python
budget = Σ XP_BUDGET[pc_level][difficulty] − Σ CR_XP[ally_cr]

committed_xp = Σ (count × CR_XP[stat_id]) for each {id, count} in required
required_count = Σ count for each entry in required
```

XP for each stat block is derived from its `cr:X` tag via the internal `CR_XP` table. Neither the budget nor any XP value is ever emitted in output.

#### Phase 2: Generate candidate solutions

The algorithm treats the budget as a watermark and moves toward it from whatever the committed XP is. Both directions (over and under) use the same output structure — a list of candidate solutions sorted by closeness to the budget, each carrying an optional remark.

**If committed_xp > budget — reduce required**

For each required entry with `count > 1`, compute the maximum count that keeps total committed XP ≤ budget (all other entries unchanged):

```python
reduced = floor((budget - sum_xp_of_other_entries) / xp_of_this_entry)
# include only if reduced >= 1
```

Each valid reduction is one candidate solution. **Always include the original requested lineup** as a candidate (the DM may want PCs to face an impossible enemy with a narrative way out planned, for drama reasons).

- *If any reduction brings total XP in-budget*: the best in-budget reduction is surfaced first; the original is emitted as a later option with the remark "Over requested XP budget; do not use without narrative safeguards".
- *If no reduction is possible* (all required counts are 1, or no reduction lands in-budget): emit only the original with the remark "⚠ required monster(s) alone exceed budget — no reduction possible".

**If committed_xp ≤ budget — fill up**

`remaining = budget − committed_xp`

*With optional candidates*: sample up to 3 fill combinations using weighted randomization (Phase 3). Each combination is one candidate solution.

*Without optional candidates* (empty list): for each required entry, try adding more of it:

```python
extra = floor(remaining / xp_of_this_entry)
# if extra >= 1: solution = required with this entry count += extra
```

Each viable addition is one candidate solution. This path exists specifically for cases like "20 zombies required, no optionals — add more zombies."

#### Phase 3: Weighted sampling for optional fill

Weight each optional candidate by its rank position (harmonic decay):

```
weight[i] = 1 / (i + 1)
# optional[0] → 1.0, optional[1] → 0.5, optional[2] → 0.33, …
```

For each of 3 independent samples:
1. Sample without replacement using these weights to select **up to 2 stat block types** (DMG: 2–3 distinct stat blocks per encounter is the manageable ceiling)
2. For each selected type, greedily assign count to spend remaining budget:

```python
count = max(1, floor(remaining / xp))
remaining -= count * xp
```

3. Stop adding types once remaining < cheapest remaining optional XP

The result is a fill combination (list of `{id, count}`) appended to required to form a complete candidate solution.

#### Phase 4: Rank and emit

Sort all candidate solutions by `abs(total_xp − budget)`. Ties broken by putting under-budget solutions before over-budget ones (the DMG says don't exceed budget; being slightly under is fine). This ensures that when both a reduced in-budget solution and the original over-budget lineup exist, the reduced one appears first.

Deduplicate (same set of `{id, count}` pairs). Emit up to 3 solutions, each as a count table followed by an optional remark line.

**Remark selection**: For over-budget solutions, the remark depends on whether reduction was possible. If the reduce path could produce at least one in-budget reduction (i.e. at least one required entry had `count > 1` and a valid reduced count), use "Over requested XP budget; do not use without narrative safeguards" for the original lineup. If no reduction was possible, use the "no slim-down possible" remark.

**Monster count cap**: When emitting each solution, compute `party_size = len(pcs) + len(allies)`. If `total_monster_count / party_size > 4`, append the monster-count warning to that solution's remark (in addition to any other remark). This warns that action economy may make the encounter harder than XP math suggests.

**Remark conditions**:

| Condition | Remark |
|---|---|
| total_xp > budget (reduction was possible; this is the original requested lineup) | "Over requested XP budget; do not use without narrative safeguards" |
| total_xp > budget (no reduction possible — all required counts are 1) | "⚠ required monster(s) alone exceed budget — no reduction possible" |
| total_xp < 50% of budget | "budget largely unspent — consider higher-CR optional candidates" |
| No fill was possible (remaining > 0, no optional, no required extras) | "no optional candidates provided; consider using kb with-tag to discover candidates first" |
| Total monster count / party size > 4 | "You have more than the recommended number of enemies per ally; this encounter may be harder than CR math suggests, consider lowering enemy count" |

**Output format**:

```
Encounter Proposals
Line format: [creature qty] stat.id ..tags..

> Option A (any remarks here)
[1] stat.wight cr:3 type:undead size:medium habitat:any
[4] stat.ghoul cr:1 type:undead size:medium habitat:any

```

### Edge cases

| Situation | Behaviour |
|---|---|
| `required` is empty, `optional` is non-empty | Committed XP = 0; all fill comes from optional |
| Both `required` and `optional` are empty | Emit error: nothing to build an encounter from |
| Required entry has no `cr:` tag | Treat its XP as 0 (skip from budget math); include in proposals; note in output |
| Optional candidate has no `cr:` tag or not found in KB | Skip silently; note in output header |
| Ally XP ≥ budget | Budget ≤ 0; note "Allies alone may outmatch this encounter"; emit required-only if non-empty |
| All candidates produce total XP < 50% of budget | Emit best available, remark on unspent budget |

---

## Worked Examples

### Example 1 — Undead cemetery (pure optional, no fixed requirement)

Four Level 5 PCs explore an old cemetery at night. No allies. Moderate difficulty.

**`kb with-tag` call** (with-tag output shows IDs with tags):
```
kb with-tag type:undead (cr:1 cr:2 cr:3 cr:1-4 cr:1-2)
```
→ e.g. stat.ghast cr:2 type:undead, stat.ghoul cr:1 type:undead, stat.skeleton cr:1-4 type:undead, stat.specter cr:1 type:undead, stat.wight cr:3 type:undead, stat.zombie cr:1-4 type:undead, …

AI decides: no single monster is required; it wants to see wight as the anchor, with ghoul and specter as atmospheric fill. It calls:

```json
{
  "required": [],
  "optional": ["stat.wight", "stat.ghoul", "stat.specter", "stat.zombie", "stat.skeleton"],
  "difficulty": "moderate",
  "pcs": [5, 5, 5, 5]
}
```

Budget = 4 × 750 = 3,000. Fill target: ~4 additional. Weighted sampling biases toward wight and ghoul but may occasionally surface specter. Example output:

```
Encounter Proposals
Line format: [creature qty] stat.id ..tags..

> Option A
[1] stat.wight cr:3 type:undead size:medium habitat:any
[4] stat.ghoul cr:1 type:undead size:medium habitat:any

> Option B
[2] stat.ghast cr:2 type:undead size:medium habitat:any
[2] stat.specter cr:1 type:undead size:medium habitat:any

> Option C
[1] stat.wight cr:3 type:undead size:medium habitat:any
[2] stat.zombie cr:1-4 type:undead size:medium habitat:any
```

AI picks the one that fits the scene.

---

### Example 2 — Noble and her guard unit (required with counts)

Four Level 4 PCs confront a corrupt noble at a gala. The noble must be present; guards round it out. Moderate difficulty.

**`balance_encounter` call**:
```json
{
  "required": [{"id": "stat.noble", "count": 1}],
  "optional": ["stat.guard", "stat.thug", "stat.spy"],
  "difficulty": "moderate",
  "pcs": [4, 4, 4, 4]
}
```

Budget = 4 × 375 = 1,500. Noble XP = 700. Remaining = 800. Fill target ≈ 3 (1 per PC beyond the noble). Guard XP = 50. Example output:

```
Encounter Proposals
Line format: [creature qty] stat.id ..tags..

> Option A
[1] stat.noble cr:1-8 type:humanoid size:medium habitat:urban
[4] stat.guard cr:1-8 type:humanoid size:medium habitat:urban

> Option B
[1] stat.noble cr:1-8 type:humanoid size:medium habitat:urban
[2] stat.thug cr:1-2 type:humanoid size:medium habitat:urban

> Option C
[1] stat.noble cr:1-8 type:humanoid size:medium habitat:urban
[1] stat.spy cr:1 type:humanoid size:medium habitat:urban
[2] stat.guard cr:1-8 type:humanoid size:medium habitat:urban
```

---

### Example 3 — Over-budget required (reducible)

Four Level 5 PCs face a zombie horde blocking a bridge. The DM wants 80 zombies for the scene. Moderate difficulty.

**`balance_encounter` call**:
```json
{
  "required": [{"id": "stat.zombie", "count": 80}],
  "optional": [],
  "difficulty": "moderate",
  "pcs": [5, 5, 5, 5]
}
```

Budget = 3,000. Zombie XP = 50 each → 80 × 50 = 4,000 committed. Required exceeds budget. Reduction possible: floor(3,000 / 50) = 60 zombies brings total in-budget.

Output:
```
Encounter Proposals
Line format: [creature qty] stat.id ..tags..

> Option A
[60] stat.zombie cr:1-4 type:undead size:medium habitat:any

> Option B (Over requested XP budget; do not use without narrative safeguards)
[80] stat.zombie cr:1-4 type:undead size:medium habitat:any
```

The reduced lineup (Option A) is always first when reduction is possible; the original requested set (Option B) is offered as a later option for DMs who want an overwhelming encounter with a planned narrative way out. When no reduction is possible (e.g. a single vampire, count 1), the tool emits only the original lineup with the remark "⚠ required monster(s) alone exceed budget — no reduction possible".

---

### Example 4 — Zombie horde + big baddy

Four Level 5 PCs wade into a graveyard overrun by the undead. The DM wants 20 zombies as the swarm, rounded out with something scarier. Moderate difficulty.

**`balance_encounter` call**:
```json
{
  "required": [{"id": "stat.zombie", "count": 20}],
  "optional": ["stat.wight", "stat.mummy", "stat.ghast"],
  "difficulty": "moderate",
  "pcs": [5, 5, 5, 5]
}
```

Budget = 3,000. Zombie XP = 50 each → 1,000 committed. Remaining = 2,000. Horde mode (20 > 2 × 4 = 8). Sort optional by CR descending: mummy (CR 3, 700 XP), wight (CR 3, 700 XP), ghast (CR 2, 450 XP). Greedily fill with 1–2 big baddies:

```
Encounter Proposals
Line format: [creature qty] stat.id ..tags..

> Option A
[20] stat.zombie cr:1-4 type:undead size:medium habitat:any
[1] stat.mummy cr:3 type:undead size:medium habitat:desert habitat:any
[1] stat.wight cr:3 type:undead size:medium habitat:any

> Option B
[20] stat.zombie cr:1-4 type:undead size:medium habitat:any
[2] stat.ghast cr:2 type:undead size:medium habitat:any
```

## File Layout

All encounter calculator code lives in a single new file:

```
lens/core/operators/encounter_calc.py
```

It registers the `balance_encounter` tool at module import time (the `tools.py` autodiscovery mechanism picks it up from `lens/core/operators/`):

```python
register_operator_tool(
    "balance_encounter",
    OperatorToolDef(
        parameters=balance_encounter_SCHEMA,
        prompt_snippet=(
            "Use balance_encounter to generate up to three balanced encounter proposals from a "
            "ranked candidate list. Pass PC levels explicitly from context (level:N tags on pinned "
            "pc.* objects) and ally CRs if any allies fight alongside the party. "
            "The tool uses D&D 2024 XP budget math (no monster-count multiplier)."
        ),
        keep_text=True,
    ),
    _invoke_balance_encounter,
    limited_to_datasets=["dnd"],
)
```

No new CLI commands are needed. No new KB object types. No changes to existing operators.

### Constants and tables

The XP budget table, CR-to-XP table, and CR tag ordering are module-level constants in `encounter_calc.py`, making them easy to audit or update against the printed 2024 DMG.

---

## System Prompt Snippet for Operators

The DM-facing guidance (how to actually USE these tools during a session) belongs in a KB object — likely `design.encounter`. That object is out of scope for this design but should say something like:

> When planning a combat encounter: use kb with-tag (with OR groups for CR sets, habitat, type) or kb list-tags to discover stat block candidates. Rank results by narrative fit. Call balance_encounter with your ranked list, the PC levels from their pinned objects, and any allied creatures. Pick a proposal and narrate.

---

## Implementation Checklist

- [ ] Add `level:N` tag to all `pc.*` objects in the test dataset (`datasets/testing/`)
- [ ] Write `lens/core/operators/encounter_calc.py` with:
  - [ ] `CR_TAG_ORDER` — ordered list of `(float, "cr:tag")` pairs
  - [ ] `CR_XP` — dict mapping CR float to XP int (internal only; never emitted)
  - [ ] `XP_BUDGET` — nested dict `{level: {difficulty: xp}}` (internal only; never emitted)
  - [ ] `cr_tag_to_float()` — `"1-4"` → `0.25` (tag format → float)
  - [ ] `cr_str_to_float()` — `"1/4"` → `0.25` (ally parameter format → float)
  - [ ] `_name_from_id()` — `"stat.adult-white-dragon"` → `"Adult White Dragon"`
  - [ ] `_stat_xp()` — look up XP for a stat block ID via its `cr:` tag
  - [ ] `_reduce_candidates()` — for each over-budget required entry with count > 1, generate reduced solutions; always include original lineup when any reduction is possible; always include the original lineup as a candidate when any reduction is possible
  - [ ] `_weighted_sample()` — sample without replacement using harmonic-decay weights; returns up to 2 optional types per call
  - [ ] `_fill_candidates()` — 3 independent weighted samples from optional (or extra-required if no optional); returns fill combinations
  - [ ] `_rank_solutions()` — sort by abs(total_xp − budget), ties: under before over; deduplicate
  - [ ] `_invoke_balance_encounter()` — async tool handler; emits count tables, no XP; applies remark selection (reduction possible vs not) and monster count cap; applies remark selection (reduction possible vs not) and monster count cap per solution
  - [ ] `register_operator_tool()` for balance_encounter only
- [ ] Add unit tests in `lens/test/test_encounter_calc.py`:
  - [ ] Budget calculation for various party compositions and difficulties
  - [ ] Ally XP reduction (including reduction to zero)
  - [ ] CR tag ↔ float round-trip (both directions)
  - [ ] Reduce path: over-budget required with reducible counts → reduced solutions sorted by closeness
  - [ ] Reduce path: single required monster already over budget → original returned with remark, no reduction possible
  - [ ] Fill path (optional): 3 weighted samples produce distinct proposals; lower-ranked candidates can appear
  - [ ] Fill path (no optional): extra-required fill used; produces at least 1 solution
  - [ ] Ranking: solutions sorted by abs distance; under-budget before over-budget at equal distance
  - [ ] Remark conditions: over-budget (reduction possible vs not), budget < 50%, no fill possible, monster count cap
  - [ ] Edge cases: empty required, empty optional, both empty
- [ ] Run `poe check` (lint + typecheck + tests)