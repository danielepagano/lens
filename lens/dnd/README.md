# D&D (reference dataset)

The **`dnd`** bundled dataset adds D&D 2024 **reference** content: spells, monsters (stat blocks), equipment, and a **`rules.system`** file that overrides the stub shipped in **`rpg`**. It also unlocks **`lens dnd balance`** and the `balance_encounter` design tool.

RPG operators (`play`, `advance`) live in the **`rpg`** dataset; use **both** `rpg` and `dnd` for typical D&D campaigns. See [RPG Design Doc](../../docs/rpg-design.md) and [lens/rpg/README.md](../rpg/README.md).

## Enabling

```toml
[project]
narrative = "my-campaign"
datasets  = ["rpg", "dnd"]
```

Put `dnd` **after** `rpg` so `rules.system` and reference objects from `dnd` shadow the core bundle.

## What’s in `datasets/dnd/`

- **`rules/system.md`** — D&D 2024 rules reference for the AI (id `rules.system`)
- **`spell/`**, **`stat/`**, **`equipment/`** — KB corpora and `tags.toml` indexes

Project-local knowledge overrides dataset items; mutating a dataset object creates a local copy (copy-on-write).

## `lens dnd balance`

Balanced combat encounter proposals from PC levels, difficulty, and ranked stat-block candidates. Only when `dnd` is in `datasets`. Uses D&D 2024 DMG-style XP budgets internally.

```bash
echo '{"difficulty": "moderate", "pcs": [3, 3], "required": [{"id": "stat.ghast", "count": 1}], "optional": ["stat.ghoul", "stat.skeleton"], "allies": ["1"]}' | lens dnd balance
lens dnd balance --input encounter_params.json
```

JSON fields:

- `required` — `[{ "id": "stat.xyz", "count": N }]`
- `optional` — stat block IDs (ranked)
- `difficulty` — `"low"` | `"moderate"` | `"high"`
- `pcs` — PC levels
- `allies` — optional ally CR strings (e.g. `["1/2", "2"]`)

## `lens play`

Implemented in **`lens.rpg`**; requires the **`rpg`** dataset. With D&D content, pin **`rules.system`** (D&D body when `dnd` follows `rpg`), **`rules.rpg`**, and at least one **`pc.*`**.

```bash
lens play "the party enters a dimly lit tavern"
lens play -p rules.system -p rules.rpg -p pc.hero
```

See [CLI reference](../cli/README.md#ai-operators) for `--pin`, `--unpin`, `--llm`, `--retry`, `-as`.

## D&D Beyond extractor (`tools/ddb-extract/`)

Extracts D&D Beyond content into Lens KB Markdown. Output feeds `datasets/dnd/` via `lens kb extract`. See [tools/ddb-extract/README.md](../../tools/ddb-extract/README.md).
