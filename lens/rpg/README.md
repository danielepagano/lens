# RPG (core dataset)

The **`rpg`** bundled dataset is the ruleset-agnostic layer for tabletop-style play in Lens: `rules.rpg`, a default `rules.system` stub, templates (`pc`, `location`, `npc`, …), and `design.*` modules. Operators **`play`** and **`advance`** are gated on this dataset.

See [RPG Design Doc](../../docs/rpg-design.md) and the main [CLI reference](../cli/README.md).

## Enabling

```toml
[project]
narrative = "my-campaign"
datasets  = ["rpg"]
```

List a specialized rule system dataset after `rpg` to override `rules.system`. Example:

```toml
datasets = ["rpg", "<your-ruleset-dataset>"]
```

(Later entries in `datasets` shadow earlier ones.)

## How `lens play` works

`play` is a **session operator**: the first call creates a sub-node (e.g. `play-combat-engage-the-goblins`) and auto-pins `rules.system` and `rules.rpg` into its front matter. Subsequent calls inside the session append new inline blocks. Use `--end` to close the session and return to the parent.

**Requirements** (checked at generation time, not session creation):
- At least one `pc.*` object pinned (at any ancestor level)
- `rules.system` and `rules.rpg` (auto-pinned by the session)

**Modules**: `--module <key>` pins `rules.<key>` (e.g. `rules.combat`, `rules.downtime`) into the session. Only one extra module is active at a time; switching swaps it out. Use `lens section` + a new `play` call to nest sessions with different modules.

Default: append one or more player lines (blockquotes) without calling the GM / LLM — useful when several characters act before narration. `@mentions` in the prompt are dumped as `KnowledgeObject`-formatted text inside an HTML comment for later reference.

**`--pass`**: call the GM / LLM to respond, writing a `[play]...[/play]` block containing only GM output. With no prompt text, it generates a GM response based on the current passage.

