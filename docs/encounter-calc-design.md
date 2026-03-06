# Encounter Calculator Design

> Status: Design (not yet implemented)

## Overview

When the DM describes a narrative situation — zombies rising in a cemetery, bandits blocking the road — the AI needs to find and assemble an appropriate set of monsters without loading every stat block into context. This subsystem provides two LLM-callable tools that close that gap:

1. **`encounter_search`** — finds stat block IDs matching a CR range, habitat, and monster type, returning a compact table (no stat block bodies)
2. **`encounter_build`** — takes the AI's ranked candidate list plus party composition and produces up to three balanced encounter proposals using D&D 2024 XP budget math

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
  ├─ AI ranks candidates by narrative fit
  │    (e.g. zombie > ghoul > wight for a cemetery scene)
  │
  ├─ AI calls encounter_build(candidates, difficulty, pcs, allies)
  │    → up to 3 encounter proposals with monster counts and XP breakdown
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

The budget for an encounter = sum of each PC's budget at their level for the requested difficulty. These numbers match the D&D 2024 DMG encounter-building table (which aligns closely with the 2014 easy/medium/hard thresholds — confirm against physical 2024 DMG pp. 111–112 during implementation).

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
| 14 | 2,900 | 4,900 | 6,300 |
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

### Difficulty classification

After computing total monster XP, the tool classifies the actual difficulty by comparing against all three budget thresholds for the given party (useful for proposals that land off-target):

```
if monster_xp < low_budget:     "Trivial"
if monster_xp < moderate_budget: "Low"
if monster_xp < high_budget:     "Moderate"
else:                             "High"
```

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

Given the AI's ranked list of preferred stat block IDs, the party composition, and a desired difficulty, compute up to three balanced encounter proposals. The proposals aim to hit the XP budget while exploring different monster mixes.

### JSON Schema (parameters)

```json
{
  "type": "object",
  "properties": {
    "candidates": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Ranked list of stat block IDs in preference order (most narratively fitting first). Up to 6 candidates. Example: ['stat.zombie', 'stat.ghoul', 'stat.wight']."
    },
    "difficulty": {
      "type": "string",
      "enum": ["low", "moderate", "high"],
      "description": "Target encounter difficulty."
    },
    "pcs": {
      "type": "array",
      "items": {"type": "integer", "minimum": 1, "maximum": 20},
      "description": "List of PC levels, one integer per PC. Example: [5, 5, 5, 5] for a party of four level-5 characters."
    },
    "allies": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Optional list of ally CRs (as fraction strings) that fight alongside the party and reduce the monster budget. Example: ['1/2', '2']. Omit or pass [] if no allies."
    }
  },
  "required": ["candidates", "difficulty", "pcs"]
}
```

### Implementation

#### Phase 1: Compute the budget

```python
def compute_budget(pcs: list[int], difficulty: str, allies: list[str]) -> int:
    budget = sum(XP_BUDGET[level][difficulty] for level in pcs)
    ally_xp = sum(CR_XP[cr_str_to_float(cr)] for cr in (allies or []))
    return max(0, budget - ally_xp)
```

`cr_str_to_float` converts `"1/4"` → `0.25`, `"1/2"` → `0.5`, `"1"` → `1.0`, etc.

#### Phase 2: Look up candidate XP values

```python
def candidate_xp(stat_id: str, kb: KnowledgeStore) -> float | None:
    tags = kb.get_tags(stat_id)
    cr_str = _tag_value(tags, "cr")    # e.g. "1-4"
    if not cr_str:
        return None
    cr_val = cr_tag_to_float(cr_str)   # e.g. 0.25
    return CR_XP.get(cr_val)
```

`cr_tag_to_float` converts the stored tag format: `"1-4"` → `0.25`, `"1-2"` → `0.5`, `"1"` → `1.0`, etc.

#### Phase 3: Generate proposals

Three proposal strategies are attempted in order. Each is only included if it produces a valid (non-zero) encounter:

**Strategy A — Primary focus**: Fill the budget primarily with `candidates[0]`, supplementing with `candidates[1]` and `candidates[2]` if needed to approach the budget.

**Strategy B — Secondary focus**: Fill primarily with `candidates[1]` (or `candidates[0]` if only one candidate), supplement with adjacent candidates.

**Strategy C — Broadest mix**: Distribute XP budget across all candidates proportionally, from highest-ranked (most budget) to lowest-ranked (least budget). This produces the most varied lineup.

For each strategy, the monster count per type is computed as:

```python
count = max(1, round(allocated_xp / candidate_xp_per_monster))
```

Where `allocated_xp` is the share of the total budget assigned to that monster type in the strategy.

After computing counts:
- Round each count down so total XP does not massively overshoot (> 150% of budget)
- If total XP < 25% of budget for a strategy, skip it (not a meaningful encounter)
- Classify the actual difficulty for each proposal (trivial / low / moderate / high)

#### Phase 4: Emit proposals

```
## Encounter Proposals

**Party**: 4 × Level 5
**Difficulty**: Moderate
**XP Budget**: 3,000 XP (4 × 750)
**Ally reduction**: none

---

### Option A — Undead Horde (zombie-forward)
- 6 × stat.zombie (CR 1/4 · 50 XP each) → 300 XP
- 9 × stat.ghoul (CR 1 · 200 XP each) → 1,800 XP
- 1 × stat.wight (CR 3 · 700 XP) → 700 XP
- **Total**: 2,800 XP | **Actual difficulty**: Moderate ✓

### Option B — Pack Hunters (ghoul-forward)
- 3 × stat.ghoul (CR 1 · 200 XP each) → 600 XP
- 2 × stat.wight (CR 3 · 700 XP each) → 1,400 XP
- 8 × stat.zombie (CR 1/4 · 50 XP each) → 400 XP
- **Total**: 2,400 XP | **Actual difficulty**: Low (slightly under)

### Option C — Elite Guard (wight-forward)
- 4 × stat.wight (CR 3 · 700 XP each) → 2,800 XP
- 4 × stat.zombie (CR 1/4 · 50 XP each) → 200 XP
- **Total**: 3,000 XP | **Actual difficulty**: Moderate ✓
```

The AI reads these proposals, picks one, and writes the encounter narrative around it.

### Edge cases

| Situation | Behaviour |
|---|---|
| Single candidate only | All 3 proposals use only that monster at different counts (× budget_low, × budget_moderate, × budget_high) |
| Candidate has no `cr:` tag | Skip that candidate with a warning line in output |
| Budget ≤ 0 after ally reduction | Report that allies alone outmatch the encounter; propose 1 token weak monster |
| All proposals produce < 25% budget coverage | Report that the CR range is too low for this party; suggest higher CRs |
| Candidate stat ID not found in KB | Skip with warning |

---

## Worked Example

**Situation**: Four Level 5 PCs explore an old cemetery at night. No allies. The DM wants a Moderate difficulty combat with undead.

**Step 1 — AI estimates CR range**

For a Moderate encounter, appropriate CR ≈ party level × (2/3) ≈ 3. Search CR 0 to 5 to allow variety including low-CR horde monsters.

**Step 2 — `encounter_search` call**

```json
{
  "cr_min": "0",
  "cr_max": "5",
  "monster_type": "undead"
}
```

Result (subset):
```
| stat.ghoul         | Ghoul         | 1   | undead | medium | any      |
| stat.ghast         | Ghast         | 2   | undead | medium | any      |
| stat.skeleton      | Skeleton      | 1-4 | undead | medium | any      |
| stat.specter       | Specter       | 1   | undead | medium | any      |
| stat.wight         | Wight         | 3   | undead | medium | any      |
| stat.zombie        | Zombie        | 1-4 | undead | medium | any      |
| stat.mummy         | Mummy         | 3   | undead | medium | desert, any |
```

**Step 3 — AI ranks by narrative fit**

For a dark cemetery scene: zombie (1st — thematic horde), ghoul (2nd — hunter threat), wight (3rd — elite commander)

**Step 4 — `encounter_build` call**

```json
{
  "candidates": ["stat.zombie", "stat.ghoul", "stat.wight"],
  "difficulty": "moderate",
  "pcs": [5, 5, 5, 5]
}
```

Budget = 4 × 750 = 3,000 XP.

Output (three proposals as shown in the format above).

**Step 5 — AI picks and narrates**

The AI selects Option C (elite guard) because a wight commander leading zombie thralls fits the cemetery aesthetic with good dramatic tension. It writes the encounter: the wight directs, zombies form a wall, ghouls lurk in the shadows.

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
  - [ ] `CR_XP` — dict mapping CR float to XP int
  - [ ] `XP_BUDGET` — nested dict `{level: {difficulty: xp}}`
  - [ ] `cr_tag_to_float()` — `"1-4"` → `0.25`
  - [ ] `cr_str_to_float()` — `"1/4"` → `0.25` (for ally parameter)
  - [ ] `_name_from_id()` — `"stat.adult-white-dragon"` → `"Adult White Dragon"`
  - [ ] `_invoke_encounter_search()` — async tool handler
  - [ ] `_invoke_encounter_build()` — async tool handler
  - [ ] `register_operator_tool()` calls for both tools
- [ ] Add unit tests in `lens/test/test_encounter_calc.py`:
  - [ ] Budget calculation for various party compositions and difficulties
  - [ ] Ally XP reduction (including reduction to zero)
  - [ ] CR tag ↔ float round-trip
  - [ ] Search tag filtering logic (can be tested against the testing dataset)
  - [ ] Proposal generation with 1, 2, and 3 candidates
  - [ ] Edge cases: no candidates found, single candidate, all-low-CR candidates vs high-level party
- [ ] Run `poe check` (lint + typecheck + tests)

---

## Open Questions

**1. Monster count cap**: Should the tool enforce a maximum per-monster-type count (e.g. 15)? A 60-zombie horde is mathematically correct but may be narratively absurd. Current design leaves this to the AI's judgment — the tool reports any count, and the AI can modulate. A soft warning ("> 12 of one type — consider a higher-CR alternative") might be useful.

**2. Multiple habitats per monster**: The search already handles this since `get_ids_with_tag("habitat:urban")` returns any monster tagged with that habitat. No special handling needed.

**3. Type `or-small-humanoid` and similar compound tags**: Tags like `type:or-small-humanoid` exist for shapeshifters. The type filter does exact matching on the tag value, so searching `monster_type: "humanoid"` would miss these. An option: also query `type:or-small-humanoid` when `monster_type` is `"humanoid"`. Or leave it — these are edge cases.

**4. `encounter_search` vs `kb with-tag`**: The existing `kb with-tag` CLI command already supports tag queries. The `encounter_search` tool is a specialized version that (a) handles CR ranges across multiple tags, (b) formats output as a compact table rather than full KB object content, and (c) is callable by the LLM mid-session. There is intentional overlap; the CLI command remains for human use.

**5. D&D 2024 budget table accuracy**: The table in this document is derived from the referenced calculator (which uses 2014 thresholds) with the multiplier removed. Verify the Moderate column against the printed 2024 DMG encounter-building table during implementation — the 2024 DMG may have revised some values.

**6. `size` as a search filter**: Size is not included as a search parameter (not obviously useful for encounter design). Add it as an optional parameter if a use case emerges.
