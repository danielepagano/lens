# D&D Dataset (`lens-dnd`)

Rules, stat blocks, spells, and encounter-building tools from D&D 5.5e SRD.

> This work includes material from the System Reference Document 5.2.1 ("SRD 5.2.1") by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode.

## Enabling

Requires the Lens `rpg` dataset. List `lens-dnd` **after** `rpg` so `rules.system`, `design.encounter`, and related objects shadow the core RPG bundle.

```toml
[project]
datasets = ["rpg", "lens-dnd"]
```

## Content organization

| Directory | Contents |
|-----------|----------|
| `knowledge/stat/` | ~310 monster stat blocks (aboleth through zombie), each tagged with `cr:`, `type:`, `size:`, `habitat:` |
| `knowledge/spell/` | ~175 D&D 2024 spells, tagged with `level:`, `school:`, `ritual` |
| `knowledge/feature/` | ~20 class and species features (SRD-only) |
| `knowledge/equipment/` | ~45 weapons, armors, and shields, tagged with `category:` |
| `knowledge/rules/system.md` | D&D rules reference for AI DM (d20 system, actions, combat, resting, conditions) |
| `knowledge/rules/encounter.md` | Encounter running procedures (spatial tracking, initiative flow, pacing, resolution) |
| `knowledge/design/encounter.md` | Design module for `lens design --module encounter` |
| `knowledge/encounter/_template.md` | KB template for `encounter.*` objects |
| `knowledge/tracker/_template.md` | KB template for `tracker.*` initiative trackers |
| `knowledge/tags.toml` | Bidirectional tag index (CR × stat blocks, school × spells, category × equipment, etc.) |

## Encounter support

The dataset provides five integrated layers for designing and running encounters:

### 1. Design module — `knowledge/design/encounter.md`

Loaded by `lens design --module encounter`. Tagged `rules.system`, so opening the module also brings the D&D rules reference into context — modules resolve with `+`. Guides the LLM through a structured workflow:

1. **Story service check** — connect the encounter to active fronts and PC story threads
2. **Situation gathering** — scene, participants, stakes, secrets
3. **Combat balancing** — discover stat blocks by tag (`kb_with_tag`), invoke the `balance_encounter` tool with PC levels (`level:N` from pinned `pc.*` objects) and optional ally stat blocks (`stat.*`), then present the `KB['stat.…']` roster in Prep
4. **Write the encounter object** — three mandatory sections (Situation, Running non-PC characters, Prep and reference) with AI-secret encoding for hidden information
5. **Tagging convention** — every `stat.*` in Prep must also be a tag on the `encounter.*` object so `encounter.some-scene+` pulls stat blocks into play context

Encounter types covered: combat, social, chase/escape, puzzle/exploration, and mixed (with phase triggers).

### 2. Encounter template — `knowledge/encounter/_template.md`

KB template for creating `encounter.*` objects. Three sections:

- **`## Situation`** — what's happening, stakes, initial positions (distances, formations, cover), scene rules, triggers, resolution conditions
- **`## Running non-PC characters`** — encounter-specific tactics, priorities, morale, flee thresholds (defaults: player runs dice, AI answers when asked, grounded in stat blocks)
- **`## Prep and reference`** — combat-only `KB['stat.…']` roster with counts (foes and allied stat blocks). Every stat listed here must also appear as an object tag

### 3. Running rules — `knowledge/rules/encounter.md`

Runtime procedures for the AI DM during play:

- **Spatial awareness** — theater-of-mind tracking at 5-ft resolution, zones, cover, elevation, restating after significant changes
- **Initiative and turn structure** — the player runs all dice and tracks turn order; the AI controls creature choices when meaningful tactical decisions arise
- **Encounter flow** — entry → mid-encounter triggers → resolution → post-encounter consequences

### 4. Balance tool — `balance_encounter`

An LLM command tool (invoked by `design --module encounter`) and standalone CLI command:

**`balance_encounter` (LLM tool)** — called during the design module's combat balancing step. Accepts:
- `required` — must-include stat blocks with counts
- `optional` — ranked candidate list to fill remaining budget
- `difficulty` — low / moderate / high (single-encounter XP budget per D&D 2024)
- `pcs` — array of PC levels (one per party member)
- `allies` — allied stat blocks in `{id, count}` form; their `cr:` tags add XP to the budget

Returns up to three encounter proposals sorted by XP-budget fit, with warnings for oversized enemy groups or insufficient candidates.

```bash
# Standalone CLI equivalent (JSON on stdin):
echo '{ "required": [{"id": "stat.zombie", "count": 10}],
        "optional": ["stat.wight", "stat.ghast"],
        "difficulty": "moderate",
        "pcs": [5, 5, 5, 5],
        "allies": [] }' | lens dnd balance
```

### 5. Initiative tracker — `knowledge/tracker/_template.md`

KB template for `tracker.*` objects — static interactive initiative trackers rendered as `<details>` HTML:

- Every combatant is a `<details>` element sorted by initiative (descending)
- PCs: Active `[x]` marker, reaction check, conditions textarea
- Monsters/NPCs: AC, HP counters, resource trackers (legendary resistances, legendary actions, recharge abilities, per-day spells)
- NPCs with stat blocks linked as `[Name](kb/npc.xxx) ([stat](kb/stat.xxx))`
- Delivered via LLM tool output with `kb-details: true` frontmatter for master/detail view

## Commands and tools

- **`lens dnd balance`** — JSON input, encounter proposals output (XP budget math)
- **`balance_encounter`** — LLM command tool for `lens design --module encounter` (dataset-gated; available only when `lens-dnd` is active)
