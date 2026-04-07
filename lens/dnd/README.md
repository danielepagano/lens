# lens/dnd — D&D balance encounter tool

This package (`lens.dnd`) provides the **`lens dnd balance`** command. It is gated on
the dataset name **`lens-dnd`** — point your project at a D&D reference dataset repo
(e.g. `lens-dnd`) and add it to `datasets`.

RPG operators (`play`, `advance`) live in the **`rpg`** package; use **both** `rpg` and
`lens-dnd` for typical D&D campaigns. See [RPG Design Doc](../../docs/rpg-design.md) and
[lens/rpg/README.md](../rpg/README.md).

## Enabling

```toml
[project]
narrative = "my-campaign"
datasets  = ["rpg", "lens-dnd"]
```

Put `lens-dnd` **after** `rpg` so `rules.system` and reference objects shadow the core bundle.

The `lens-dnd` dataset repository is separate from this package. Clone it as a sibling of
the `lens` repo (or configure its path in `lens.local.toml`) so Lens can find it by name.

## `lens dnd balance`

Balanced combat encounter proposals from PC levels, difficulty, and ranked stat-block candidates. Only when `lens-dnd` is in `datasets`. Uses D&D 2024 DMG-style XP budgets internally.

```bash
echo '{"difficulty": "moderate", "pcs": [3, 3], "required": [{"id": "stat.ghast", "count": 1}], "optional": ["stat.ghoul", "stat.skeleton"], "allies": [{"id": "stat.guard", "count": 2}]}' | lens dnd balance
lens dnd balance --input encounter_params.json
```

JSON fields:

- `required` — `[{ "id": "stat.xyz", "count": N }]`
- `optional` — stat block IDs (ranked)
- `difficulty` — `"low"` | `"moderate"` | `"high"`
- `pcs` — PC levels
- `allies` — optional allied combatants, same shape as `required` (e.g. `[{ "id": "stat.guard", "count": 4 }]`)

## `lens play`

Implemented in **`lens.rpg`**; requires the **`rpg`** dataset. With D&D content, pin **`rules.system`** (D&D body when `dnd` follows `rpg`), **`rules.rpg`**, and at least one **`pc.*`**.

```bash
lens play "the party enters a dimly lit tavern"
lens play -p rules.system -p rules.rpg -p pc.hero
```

See [CLI reference](../cli/README.md#ai-operators) for `--pin`, `--unpin`, `--llm`, `--retry`, `-as`.

## Importing KB objects from Markdown

To merge many KB objects from Markdown files that use fenced `kb` code blocks, run `lens kb extract <path>…` from your Lens project root. See the `kb` command in the [CLI reference](../cli/README.md).
