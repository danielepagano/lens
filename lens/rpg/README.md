# RPG (core dataset)

The **`rpg`** bundled dataset is the ruleset-agnostic layer for tabletop-style play in Lens: `rules.rpg`, a default `rules.system` stub, templates (`pc`, `location`, `npc`, …), and `design.*` modules. Operators **`play`** and **`advance`** are gated on this dataset.

See [RPG Design Doc](../../docs/rpg-design.md) and the main [CLI reference](../cli/README.md).

## Enabling

```toml
[project]
narrative = "my-campaign"
datasets  = ["rpg"]
```

List **`dnd` after `rpg`** when you want D&D 2024 reference content and a full `rules.system` override:

```toml
datasets = ["rpg", "dnd"]
```

(Later entries in `datasets` shadow earlier ones.)

## How `lens play` works

`play` is a **session operator**: the first call creates a sub-node (e.g. `play-combat-engage-the-goblins`) and auto-pins `rules.system` and `rules.rpg` into its front matter. Subsequent calls inside the session append new inline blocks. Use `--end` to close the session and return to the parent.

**Requirements** (checked at generation time, not session creation):
- At least one `pc.*` object pinned (at any ancestor level)
- `rules.system` and `rules.rpg` (auto-pinned by the session)

**Modules**: `--module <key>` pins `rules.<key>` (e.g. `rules.combat`, `rules.downtime`) into the session. Only one extra module is active at a time; switching swaps it out. Use `lens section` + a new `play` call to nest sessions with different modules.

**`--wait`**: append one or more player lines (blockquotes) without calling the GM / LLM — useful when several characters act before narration. `@mentions` in the prompt are dumped as `KnowledgeObject`-formatted text inside an HTML comment so the next full `play` sees spells and features without pinning them for that turn.

With `["rpg", "dnd"]`, `rules.system` resolves to the D&D rules body from the `dnd` dataset.
