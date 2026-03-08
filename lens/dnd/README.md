# D&D

Lens can use a **D&D dataset** that provides rules, stat blocks, and templates. When `dnd` is listed in `[project] datasets` in your `lens.toml`, the following commands and operators become available. See [RPG Design Doc](../../docs/rpg-design.md) for more context.

## Enabling the D&D dataset

Add `dnd` to your project's datasets:

```toml
[project]
narrative = "my-campaign"
datasets  = ["dnd"]
```

The dataset is bundled under `datasets/dnd/` in the Lens repo and provides:

- **Rules** — `rules.dnd`, `rules.engagement` (for the play operator)
- **Stat blocks** — e.g. in `knowledge/stat/`, tagged with `cr:N`, `type:...`, etc.
- **Templates** — NPC, PC, location, faction, front, lore object types

Project-local knowledge overrides dataset items; mutating a dataset object creates a local copy (copy-on-write).

## `lens dnd balance`

Calculates and proposes balanced combat encounters based on a target difficulty, character levels, and a ranked list of candidate stat block IDs. Available only when the `dnd` dataset is active. Uses the D&D 2024 DMG rules for encounter building (internal XP budgets).

```bash
# Provide JSON configuration via stdin
echo '{"difficulty": "moderate", "pcs": [3, 3], "required": [{"id": "stat.ghast", "count": 1}], "optional": ["stat.ghoul", "stat.skeleton"], "allies": ["1"]}' | lens dnd balance

# Or via a JSON file
lens dnd balance --input encounter_params.json
```

JSON fields:

- `required` — array of `{ "id": "stat.xyz", "count": N }` (monsters that must appear)
- `optional` — array of stat block IDs to fill remaining budget (ranked by preference)
- `difficulty` — `"low"` | `"moderate"` | `"high"`
- `pcs` — array of PC levels (e.g. `[5, 5, 5]`)
- `allies` — optional array of ally CR strings (e.g. `["1/2", "2"]`) that increase effective budget

## `lens play`

The **play** operator narrates in GM voice: it describes what the world does and what NPCs say and do, and stops at decision points for the player. It is only available when the `dnd` dataset is active.

You must pin:

- `rules.dnd` and `rules.engagement` (the ruleset and player–AI contract)
- At least one `pc.*` KB object (so the LLM knows who the player characters are)

Narrative output is prefixed with a player marker: `> [KEY]` where `KEY` is the pinned PC key (e.g. `pc.alice` → `[ALICE]`). With one pinned PC that key is used automatically; with multiple PCs use `-as <key>` to attribute the prompt to a specific pinned PC.

```bash
lens play "the party enters a dimly lit tavern"
lens play -p rules.dnd -p rules.engagement -p pc.hero
lens play "I rolled 18" -as alice -p pc.alice -p pc.bob
```

See the main [CLI reference](../cli/README.md#ai-operators) for shared options (`--pin`, `--unpin`, `--llm`, `--retry`). Use `-as` / `--as` to choose which pinned PC the prompt is attributed to (implies `pc.` prefix; the given key must be a pinned `pc.*`).

## D&D Beyond extractor (`tools/ddb-extract/`)

A standalone TypeScript CLI that extracts D&D Beyond content (spells, monsters, magic items, equipment) into Lens KB-formatted Markdown using Playwright + CDP. Output files are consumed by `lens kb extract` to seed or update the `datasets/dnd/` knowledge store.

See [tools/ddb-extract/README.md](../tools/ddb-extract/README.md) for setup and usage.
