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
| `knowledge/rules/system.md` | The base rules every beat needs — d20 tests, DCs, attitudes and Influence, vision and hiding, conditions, dying, resting. Always in `play` context |
| `knowledge/rules/combat.md` | Running a fight. Model-requestable module |
| `knowledge/rules/chase.md` | Running a pursuit, violent or not. Model-requestable module |
| `knowledge/rules/environment.md` | Hazards, weather, terrain, travel pace. Reached by prep |
| `knowledge/rules/encounter.md` | Usage rules for `encounter.*` — spatial tracking, controlling non-PCs, pacing, encounter flow |
| `knowledge/rules/stat.md` | Usage rules for `stat.*` — act only from the block, what the player owns |
| `knowledge/rules/tracker.md` | Usage rules for `tracker.*` — read it as canonical state, act from the named initiative down |
| `knowledge/design/encounter.md` | Design module for `lens design --module encounter` |
| `knowledge/encounter/_template.md` | KB template for `encounter.*` objects |
| `knowledge/tracker/_template.md` | KB template for `tracker.*` initiative trackers |
| `knowledge/tags.toml` | Bidirectional tag index (CR × stat blocks, school × spells, category × equipment, etc.) |

## Encounter support

The dataset provides five integrated layers for designing and running encounters:

### 1. Design module — `knowledge/design/encounter.md`

Loaded by `lens design --module encounter`. Tagged `rules.system` and `rules.encounter`, so opening the module brings both into context — modules resolve with `+`. Those two apply to every encounter; the scene-dependent rest of the shelf (`rules.combat`, `rules.chase`, `rules.environment`) is listed inside the module for `kb_get` rather than linked, because most encounters need none of it. Guides the LLM through a structured workflow:

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

## How the rules reach the model

The ruleset is **dense where it is cheap and sparse where it is expensive**. `design` thinks, runs a handful of turns, and produces what play leans on, so it gets everything. `play` answers once per beat, so it gets the base plus whatever the scene actually became.

| Object | Route | Loaded when |
|--------|-------|-------------|
| `rules.system` | modality auto-pin | every `play` beat |
| `rules.combat`, `rules.chase` | `[[dataset.modules]]` → `load_module` | the model recognises the scene turned into a fight or a pursuit; latches as `[include: …]: #` for the rest of the node |
| `rules.combat`, `rules.chase`, `rules.environment` | `+` expansion of a tag on an `encounter.*` | a prepared scene is pinned as `encounter.foo+` — no round trip, and the module drops off the `load_module` menu |
| `rules.encounter`, `rules.stat`, `rules.tracker` | `rules.<type>` companion | any `encounter.*` / `stat.*` / `tracker.*` object is pinned |
| `rules.system`, `rules.encounter` | `+` expansion of `design.encounter` | a `lens design --module encounter` session opens |
| `rules.combat`, `rules.chase`, `rules.environment` | `kb_get` by `design`, or `--include` / `@rules.*` from the user | that session's scene calls for it |
| scene-specific procedures | written into the `encounter.*` object by `design` | the encounter is in play |

Two consequences worth knowing:

- **`rules.*` objects carry no tags pointing at each other.** `play --module combat` resolves with `+` like any module pin, so a link between two rules objects would drag the second one in. Links live on `design.*` modules and on `encounter.*` objects.
- **Modules are for systems, not situations.** A fight and a chase are systems: big, structured, self-contained, with a clear trigger. A specific hazard or negotiation is a situation — known at prep time, small, different every scene — so it travels inside the prepared object instead. Every registered module costs a catalog line on every beat until it is loaded.

## Commands and tools

- **`lens dnd balance`** — JSON input, encounter proposals output (XP budget math)
- **`balance_encounter`** — LLM command tool for `lens design --module encounter` (dataset-gated; available only when `lens-dnd` is active)
