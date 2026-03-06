# Encounter Calculator Design

> Status: Design (not yet implemented)

## Overview

When the DM describes a narrative situation — zombies rising in a cemetery, bandits blocking the road — the AI needs to find and assemble an appropriate set of monsters without loading every stat block into context. This subsystem provides two LLM-callable tools that close that gap:

1. **`encounter_search`** — finds stat block IDs matching a CR range, habitat, and monster type, returning a compact table (no stat block bodies)
2. **`encounter_build`** — takes the AI's ranked candidate list plus party composition and produces up to three balanced encounter proposals using D&D 2024 XP budget math (internally; XP is never surfaced in output)

The AI uses these tools in sequence: search to discover candidates, rank them by narrative fit, then build to get balanced monster lineups. The AI then picks the best proposal and writes the encounter narratively.

Both tools are dataset-gated (`limited_to_datasets = ["dnd"]`) and are registered via the standard `register_operator_tool` mechanism, making them available inside any operator when the `dnd` dataset is active — primarily `play` and the planned `encounter` operator.

---

## User Flow

```
DM invokes play or encounter operator
  │
  ├─ AI assesses narrative situation and party composition
  │    (PCs are pinned; AI sees level:N tags from context)
  │
  ├─ AI calls encounter_search(cr_min, cr_max, habitat, monster_type)
  │    → compact table of candidate stat IDs with CR/type/size/habitats
  │
  ├─ AI decides:
  │    required  = specific stat blocks with fixed counts the scene demands
  │               (e.g. the vampire they're chasing, the noble + her guard unit)
  │    optional  = ranked list of fill-in candidates (no counts — tool decides)
  │
  ├─ AI calls encounter_build(required, optional, difficulty, pcs, allies?)
  │    → if required is already over budget: warning + slim-down alternatives
  │    → otherwise: up to 3 fill proposals in count-table format
  │
  └─ AI picks winning proposal and writes the encounter narrative
```

---

## Tag Conventions

### Existing tags on `stat.*` objects (set by `ddb-extract` / `lens kb tag`)

| Tag key | Example values | Meaning |
|---|---|---|
| `cr:X` | `cr:0` `cr:1-8` `cr:1-4` `cr:1-2` `cr:1` … `cr:30` | Challenge Rating (see CR encoding below) |
| `type:X` | `type:undead` `type:humanoid` `type:dragon` | Monster type |
| `size:X` | `size:tiny` … `size:gargantuan` | Creature size |
| `habitat:X` | `habitat:urban` `habitat:forest` `habitat:any` … | Valid habitat(s); a stat block can have multiple |

### New tag needed: `level:N` on `pc.*` objects

The DM must add a `level:N` tag to each PC KB object. The `N` is the PC's current character level (1–20). Example:

```bash
lens kb tag pc.elara -a level:5
lens kb tag pc.bodok -a level:3
```

When the AI reads the encounter context, pinned PCs appear in the `[RELEVANT KNOWLEDGE]` block with their tags visible (via `KnowledgeObject.format()`). The AI reads the levels from there and passes them explicitly to `encounter_build`.

Allied creatures (friendly NPCs, summoned beasts, etc.) are identified by their CR rather than a level. The AI identifies allies from context and passes their CRs directly.

---

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

The `encounter_search` tool accepts `cr_min` and `cr_max` as float strings (e.g. `"0.25"`, `"5"`). Internally it maps each float to the tag value it corresponds to and queries all CR tags that fall within the range.

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

D&D 2024 dropped the monster-count multiplier used in the 2014 DMG. Monster XP is summed directly and compared against the party's XP budget for the requested difficulty. This is simpler to reason about and aligns with current rules.

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

Standard D&D XP values (same across 2014 and 2024):

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

## Tool 1: `encounter_search`

### Purpose

Search `stat.*` KB objects by CR range and optional filters. Returns a compact table that the AI uses to rank candidates. Does NOT return stat block bodies — only IDs and their categorical tags.

### JSON Schema (parameters)

```json
{
  "type": "object",
  "properties": {
    "cr_min": {
      "type": "string",
      "description": "Minimum CR (inclusive) as a decimal string: '0', '0.125', '0.25', '0.5', '1', '2', ... '30'."
    },
    "cr_max": {
      "type": "string",
      "description": "Maximum CR (inclusive) as a decimal string."
    },
    "habitat": {
      "type": "string",
      "description": "Optional habitat filter. One of: arctic, coastal, desert, forest, grassland, hill, mountain, swamp, underdark, underwater, urban, any, planar-abyss, planar-nine-hells, planar-feywild, planar-shadowfell. Omit to search all habitats."
    },
    "monster_type": {
      "type": "string",
      "description": "Optional type filter. One of: aberration, beast, celestial, construct, dragon, elemental, fey, fiend, giant, humanoid, monstrosity, ooze, plant, undead. Omit to include all types."
    }
  },
  "required": ["cr_min", "cr_max"]
}
```

### Implementation

```python
async def _invoke_encounter_search(args, session, narrative, depth, on_token, on_confirm):
    cr_min = float(args["cr_min"])
    cr_max = float(args["cr_max"])
    habitat = args.get("habitat")
    monster_type = args.get("monster_type")

    kb = KnowledgeStore.for_project(session.project_root)

    # 1. Collect all CR tags within [cr_min, cr_max]
    cr_tags = [tag for (cr_val, tag) in CR_TAG_ORDER if cr_min <= cr_val <= cr_max]
    if not cr_tags:
        await on_token("No CR tags found in that range.\n")
        return

    # 2. Get stat IDs for each CR tag in range, union them
    matching: set[str] = set()
    for tag in cr_tags:
        matching.update(kb.get_ids_with_tag(tag))

    # Filter to stat.* objects only
    matching = {id for id in matching if id.startswith("stat.")}

    # 3. Optionally intersect with habitat filter
    if habitat:
        habitat_ids = set(kb.get_ids_with_tag(f"habitat:{habitat}"))
        matching &= habitat_ids

    # 4. Optionally intersect with type filter
    if monster_type:
        type_ids = set(kb.get_ids_with_tag(f"type:{monster_type}"))
        matching &= type_ids

    if not matching:
        await on_token("No stat blocks found matching the given criteria.\n")
        return

    # 5. For each match, retrieve tags and build table row
    rows = []
    for stat_id in sorted(matching):
        tags = kb.get_tags(stat_id)
        cr = _tag_value(tags, "cr")
        mtype = _tag_value(tags, "type")
        size = _tag_value(tags, "size")
        habitats = ", ".join(_tag_values(tags, "habitat"))
        name = _name_from_id(stat_id)  # "stat.adult-white-dragon" → "Adult White Dragon"
        rows.append((stat_id, name, cr, mtype, size, habitats))

    # 6. Emit markdown table
    lines = ["| ID | Name | CR | Type | Size | Habitats |",
             "|---|---|---|---|---|---|"]
    for stat_id, name, cr, mtype, size, habitats in rows:
        lines.append(f"| {stat_id} | {name} | {cr} | {mtype} | {size} | {habitats} |")

    await on_token("\n".join(lines) + "\n")
```

Helper functions:

```python
def _tag_value(tags: list[str], prefix: str) -> str:
    """Return first value after 'prefix:' in the tag list, or ''."""
    for t in tags:
        if t.startswith(f"{prefix}:"):
            return t[len(prefix)+1:]
    return ""

def _tag_values(tags: list[str], prefix: str) -> list[str]:
    """Return all values after 'prefix:' in the tag list."""
    return [t[len(prefix)+1:] for t in tags if t.startswith(f"{prefix}:")]

def _name_from_id(stat_id: str) -> str:
    """'stat.adult-white-dragon' → 'Adult White Dragon'"""
    key = stat_id.split(".", 1)[-1]
    return " ".join(word.capitalize() for word in key.split("-"))
```

### Output format (example)

```
| ID | Name | CR | Type | Size | Habitats |
|---|---|---|---|---|---|
| stat.ghoul | Ghoul | 1 | undead | medium | any |
| stat.skeleton | Skeleton | 1-4 | undead | medium | any |
| stat.specter | Specter | 1 | undead | medium | any |
| stat.wight | Wight | 3 | undead | medium | any |
| stat.zombie | Zombie | 1-4 | undead | medium | any |
```

CR values in the table use the raw tag format (`1-4` for 1/4, `1-2` for 1/2) — the AI knows how to read these.

---

## Tool 2: `encounter_build`

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

Each valid reduction is one candidate solution. Also include the original lineup as a solution (it may be closest to budget if no reduction lands closer). Collect all candidates.

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

Sort all candidate solutions by `abs(total_xp − budget)`. Ties broken by putting under-budget solutions before over-budget ones (the DMG says don't exceed budget; being slightly under is fine).

Deduplicate (same set of `{id, count}` pairs). Emit up to 3 solutions, each as a count table followed by an optional remark line.

**Remark conditions**:

| Condition | Remark |
|---|---|
| total_xp > budget | "⚠ exceeds {difficulty} budget — use intentionally or raise difficulty" |
| No slim-down possible (all required counts are 1, still over budget) | "⚠ required monster(s) alone exceed budget — no reduction possible" |
| total_xp < 50% of budget | "budget largely unspent — consider higher-CR optional candidates" |
| No fill was possible (remaining > 0, no optional, no required extras) | "no optional candidates provided; consider calling encounter_search first" |

**Output format**:

```
## Encounter Proposals

Party: 4 × Level 5 | Difficulty: Moderate

### Option A
| Count | ID | Name | CR | Type | Size | Habitats |
|---|---|---|---|---|---|---|
| 1 | stat.wight | Wight | 3 | undead | medium | any |
| 4 | stat.ghoul | Ghoul | 1 | undead | medium | any |

### Option B
| Count | ID | Name | CR | Type | Size | Habitats |
|---|---|---|---|---|---|---|
| 1 | stat.wight | Wight | 3 | undead | medium | any |
| 3 | stat.zombie | Zombie | 1-4 | undead | medium | any |
| 2 | stat.ghoul | Ghoul | 1 | undead | medium | any |

### Option C
| Count | ID | Name | CR | Type | Size | Habitats |
|---|---|---|---|---|---|---|
| 1 | stat.wight | Wight | 3 | undead | medium | any |
| 4 | stat.specter | Specter | 1 | undead | medium | any |
> budget largely unspent — consider higher-CR optional candidates
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

**`encounter_search` call**:
```json
{"cr_min": "0", "cr_max": "5", "monster_type": "undead"}
```

Result (subset):
```
| ID | Name | CR | Type | Size | Habitats |
|---|---|---|---|---|---|
| stat.ghast | Ghast | 2 | undead | medium | any |
| stat.ghoul | Ghoul | 1 | undead | medium | any |
| stat.skeleton | Skeleton | 1-4 | undead | medium | any |
| stat.specter | Specter | 1 | undead | medium | any |
| stat.wight | Wight | 3 | undead | medium | any |
| stat.zombie | Zombie | 1-4 | undead | medium | any |
```

AI decides: no single monster is required; it wants to see wight as the anchor, with ghoul and specter as atmospheric fill. It calls:

```json
{
  "required": [],
  "optional": ["stat.wight", "stat.ghoul", "stat.specter", "stat.zombie", "stat.skeleton"],
  "difficulty": "moderate",
  "pcs": [5, 5, 5, 5]
}
```

Budget = 4 × 750 = 3,000. Fill target: ~4 additional. Weighted sampling biases toward wight and ghoul but may occasionally surface specter. Three proposals emerge with different optional combinations; AI picks the one that fits the scene.

---

### Example 2 — Noble and her guard unit (required with counts)

Four Level 4 PCs confront a corrupt noble at a gala. The noble must be present; guards round it out. Moderate difficulty.

**`encounter_build` call**:
```json
{
  "required": [{"id": "stat.noble", "count": 1}],
  "optional": ["stat.guard", "stat.thug", "stat.spy"],
  "difficulty": "moderate",
  "pcs": [4, 4, 4, 4]
}
```

Budget = 4 × 375 = 1,500. Noble XP = 700. Remaining = 800. Fill target ≈ 3 (1 per PC beyond the noble). Guard XP = 50. Proposals vary: Option A might be 4 guards, Option B might be 2 thugs, Option C might be 1 spy + 2 guards — all sampled by weight.

---

### Example 3 — Over-budget required (chase scene ends in fight)

Four Level 5 PCs finally corner the vampire. Moderate difficulty requested.

**`encounter_build` call**:
```json
{
  "required": [{"id": "stat.vampire", "count": 1}],
  "optional": ["stat.zombie", "stat.skeleton"],
  "difficulty": "moderate",
  "pcs": [5, 5, 5, 5]
}
```

Budget = 3,000. Vampire XP = 10,000. Required exceeds budget.

Output:
```
⚠ Required monsters exceed the moderate budget.
  The vampire alone is a high-difficulty encounter for this party.
  Use intentionally, or switch difficulty to "high".

No slim-down available — reducing count below 1 is not possible.

### Required Lineup (over budget — use with intention)
| Count | ID | Name | CR | Type | Size | Habitats |
|---|---|---|---|---|---|---|
| 1 | stat.vampire | Vampire | 13 | undead | medium | any |
```

---

### Example 4 — Zombie horde + big baddy

Four Level 5 PCs wade into a graveyard overrun by the undead. The DM wants 20 zombies as the swarm, rounded out with something scarier. Moderate difficulty.

**`encounter_build` call**:
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
### Option A
| Count | ID | Name | CR | Type | Size | Habitats |
|---|---|---|---|---|---|---|
| 20 | stat.zombie | Zombie | 1-4 | undead | medium | any |
| 1 | stat.mummy | Mummy | 3 | undead | medium | desert, any |
| 1 | stat.wight | Wight | 3 | undead | medium | any |

### Option B
| Count | ID | Name | CR | Type | Size | Habitats |
|---|---|---|---|---|---|---|
| 20 | stat.zombie | Zombie | 1-4 | undead | medium | any |
| 2 | stat.ghast | Ghast | 2 | undead | medium | any |
```

---

## Integration with the `encounter` Operator

The `encounter` operator is already sketched in `docs/rpg-design.md`. The calculator tools are the missing mechanical layer that makes it viable.

When the `encounter` operator is built, its system prompt should:
1. Tell the AI that PCs in context have `level:N` tags visible
2. Instruct the AI to call `encounter_search` first with a CR range and habitat that matches the narrative situation
3. After ranking the search results, call `encounter_build` with the ranked candidates and explicit party array
4. Select one proposal and open the encounter sub-node with the chosen lineup

The two tools are also available inside `play` (since tools are session-wide when the `dnd` dataset is active), so the AI can initiate encounter planning mid-scene without a dedicated operator call.

---

## File Layout

All encounter calculator code lives in a single new file:

```
lens/core/operators/encounter_calc.py
```

It registers two tools at module import time (the `tools.py` autodiscovery mechanism picks it up from `lens/core/operators/`):

```python
register_operator_tool(
    "encounter_search",
    OperatorToolDef(
        parameters=ENCOUNTER_SEARCH_SCHEMA,
        prompt_snippet=(
            "Use encounter_search to find stat block IDs by CR range, habitat, and monster type. "
            "Returns a table of IDs with CR/type/size/habitat — not full stat blocks. "
            "Call this before encounter_build to discover candidates."
        ),
        keep_text=True,
    ),
    _invoke_encounter_search,
    limited_to_datasets=["dnd"],
)

register_operator_tool(
    "encounter_build",
    OperatorToolDef(
        parameters=ENCOUNTER_BUILD_SCHEMA,
        prompt_snippet=(
            "Use encounter_build to generate up to three balanced encounter proposals from a "
            "ranked candidate list. Pass PC levels explicitly from context (level:N tags on pinned "
            "pc.* objects) and ally CRs if any allies fight alongside the party. "
            "The tool uses D&D 2024 XP budget math (no monster-count multiplier)."
        ),
        keep_text=True,
    ),
    _invoke_encounter_build,
    limited_to_datasets=["dnd"],
)
```

No new CLI commands are needed. No new KB object types. No changes to existing operators.

### Constants and tables

The XP budget table, CR-to-XP table, and CR tag ordering are module-level constants in `encounter_calc.py`, making them easy to audit or update against the printed 2024 DMG.

---

## System Prompt Snippet for Operators

When the `dnd` dataset is active, both tools append their `prompt_snippet` to the operator system prompt via the existing tool-rendering path in `operator.py`. No additional system prompt engineering is needed beyond what the tools declare.

The DM-facing guidance (how to actually USE these tools during a session) belongs in a KB object — likely `rules.encounter` or a design object — that the player or DM pins when planning combat. That object is out of scope for this design but should say something like:

> When planning a combat encounter: estimate an appropriate CR range (party level × 2/3 for moderate difficulty). Call encounter_search with that range plus the narrative habitat and monster type. Rank results by fit. Call encounter_build with your ranked list, the PC levels from their pinned objects, and any allied creatures. Pick a proposal and narrate.

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
  - [ ] `_reduce_candidates()` — for each over-budget required entry with count > 1, generate a reduced solution
  - [ ] `_weighted_sample()` — sample without replacement using harmonic-decay weights; returns up to 2 optional types per call
  - [ ] `_fill_candidates()` — 3 independent weighted samples from optional (or extra-required if no optional); returns fill combinations
  - [ ] `_rank_solutions()` — sort by abs(total_xp − budget), ties: under before over; deduplicate
  - [ ] `_invoke_encounter_search()` — async tool handler
  - [ ] `_invoke_encounter_build()` — async tool handler; emits count tables, no XP
  - [ ] `register_operator_tool()` calls for both tools
- [ ] Add unit tests in `lens/test/test_encounter_calc.py`:
  - [ ] Budget calculation for various party compositions and difficulties
  - [ ] Ally XP reduction (including reduction to zero)
  - [ ] CR tag ↔ float round-trip (both directions)
  - [ ] Search tag filtering logic (can be tested against the testing dataset)
  - [ ] Reduce path: over-budget required with reducible counts → reduced solutions sorted by closeness
  - [ ] Reduce path: single required monster already over budget → original returned with remark, no reduction possible
  - [ ] Fill path (optional): 3 weighted samples produce distinct proposals; lower-ranked candidates can appear
  - [ ] Fill path (no optional): extra-required fill used; produces at least 1 solution
  - [ ] Ranking: solutions sorted by abs distance; under-budget before over-budget at equal distance
  - [ ] Remark conditions: over-budget, budget < 50%, no fill possible
  - [ ] Edge cases: empty required, empty optional, both empty
- [ ] Run `poe check` (lint + typecheck + tests)

---

## Open Questions

**1. Monster count cap**: The XP watermark approach naturally produces reasonable counts — budget / XP-per-monster gives a count that scales with the encounter tier. Hordes only appear when the DM explicitly requires them or when the optional candidates have very low CR relative to the party. The DMG note about >2 per PC variance risk could be surfaced as a remark, but it's not yet in the remark conditions table; add it if it proves useful during testing.

**2. Multiple habitats per monster**: The search already handles this since `get_ids_with_tag("habitat:urban")` returns any monster tagged with that habitat. No special handling needed.

**3. `encounter_search` vs `kb with-tag`**: The existing `kb with-tag` CLI command already supports tag queries. The `encounter_search` tool is a specialized version that (a) handles CR ranges across multiple tags, (b) formats output as a compact table rather than full KB object content, and (c) is callable by the LLM mid-session. There is intentional overlap; the CLI command remains for human use.

**4. `size` as a search filter**: Size is not included as a search parameter (not obviously useful for encounter design). Add it as an optional parameter if a use case emerges.
