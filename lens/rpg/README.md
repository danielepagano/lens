# RPG operators (`play`, `advance`)

Operators and session behaviour for the bundled **`rpg`** dataset. Dataset overview and enabling: **[datasets/rpg/README.md](../../datasets/rpg/README.md)**.

The **`rpg`** layer is ruleset-agnostic: `rules.rpg`, a default `rules.system` stub, templates (`pc`, `location`, `npc`, …), and `design.*` modules. **`play`** and **`advance`** require `rpg` in `[project] datasets`.

See [RPG design](../../docs/rpg-design.md) and the [CLI reference](../cli/README.md).

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

**Modules the GM asks for**: when an active dataset registers rules modules (`[[dataset.modules]]` in the dataset's `lens.toml`, targeting `play`), the model is offered a `load_module` tool for the ones not already in scope and may pull one in before it answers — for the scene transitions the player did not predict. Loading writes `[include: rules.<key>]: #` above the block — the only trace it leaves — so the module stays in scope for the rest of the node and survives `--retry`. Nothing to enable per project; see [configuration.md](../../docs/configuration.md#datasetmodules-dataset-lenstoml).

Default: append one or more player lines (blockquotes) without calling the GM / LLM — useful when several characters act before narration. `@mentions` in the prompt are dumped as `KnowledgeObject`-formatted text inside an HTML comment for later reference.

**`--pass`**: call the GM / LLM to respond, writing a `[play]...[/play]` block containing only GM output. With no prompt text, it generates a GM response based on the current passage.

## How `lens advance` works

`advance` is a **session operator** that moves time forward and updates whatever time moved — fronts above all, but also clocks, trackers, and any object whose own body states what a day costs it. It requires a `timeline.*` object pinned on an ancestor node (typically at the narrative root).

**Requirements**:
- At least one `timeline.*` pinned on an ancestor node

**Module**: `advance` pins **`rules.advance`** on its sub-node — its own operator module, not a design module. It used to pin `design.front`, which meant every advance carried front *authoring* instructions (timeline tag management, create/close boilerplate) that advance is forbidden to act on.

**Front discovery**: The user pins `timeline.<id>+` on the narrative root. The `+` suffix does a one-hop expansion following the timeline's dot-tags, which list the active front IDs. Fronts are automatically in context for every crawl — no manual pinning/unpinning needed.

**Lifecycle**:

| Phase | Operator | What happens |
|-------|----------|-------------|
| Create timeline | `lens kb add timeline.epic` + root pin `timeline.epic+` | One-time setup |
| Create fronts | `lens design --module front` | Creates front objects + tags them on the timeline |
| Advance time | `lens advance --days N` | Updates front content (clocks, phases). Notes resolution in summary |
| Close fronts | `lens design --module front` | Removes resolved front's tag from timeline. Creates next front |

**Advance does NOT close or retire fronts** — it only updates front content. When a front reaches resolution (all phases complete, stakes resolved), `advance` notes this in its summary block. The player then uses `lens design --module front` to close the resolved front (remove its tag from the timeline) and design the next pressure. This keeps the resolved front in context for the LLM when planning what comes next.

**Ending a front** (in a design session): Close the front by emitting a `kb` fenced code block with `id: timeline.<name>`, `remove-tags: [front.<name>]`, and empty body. This removes the front from the timeline's active set without altering its content. The resolved front stays in the KB for reference. Then create the new front and tag it on the timeline.

## The `timeline+` convention

The timeline object drives context economy. Pin `timeline.<id>+` at the narrative root:

```
kb_pin:
  - lore.world
  - pc.alice
  - timeline.epic+
```

The `+` expansion follows the timeline's dot-tags, pulling in all active fronts plus any supporting objects (locations, factions, NPCs) tagged on the timeline. Changing which fronts are active is a matter of adding/removing tags on the timeline object — done by `design`, not by editing narrative front matter.

## Prep reaches `design` and `advance`, never `play`

`design` and `advance` also **facet-expand** every root pin: a pinned `lore.world` brings `lore.world-plots`, a pinned `pc.amy` brings `pc.amy-background`. `play` never does, so the same pin set gives the GM only the play surface — no tagging, nothing pinned by hand.

**Fronts are the exception, for now.** They arrive through `timeline.<id>+` rather than as pins, and facets expand for root pins only — so `front.harbour-prep` does not ride along. `rules.advance` and `design.front` tell the model to fetch it (`kb_with_tag ["front"]`, then `kb_get`). See the *Known gap* note in [docs/rpg-design.md](../../docs/rpg-design.md#the-play-surface-and-the-prep-surface).

Either way this is what gives `advance` a definite job: it does not invent what happens next, it promotes the next prepared piece into the visible text. When prep runs out, `advance` says so and the user runs `lens design --module front`.

For the full design rationale, see [docs/rpg-design.md](../../docs/rpg-design.md) § *Front* and § *Pass The Time*.

