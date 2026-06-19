# RPG dataset (`rpg`)

Bundled rules, KB templates, and operators for **tabletop-style play** in Lens: `rules.rpg`, a default `rules.system` stub, design modules, and the **`play`** / **`advance`** operators.

## Enabling

```toml
[project]
datasets = ["rpg"]
```

Add another dataset **after** `rpg` to override `rules.system` (later entries shadow earlier ones). Use your dataset’s **folder name** as the string (often a sibling repo next to Lens — see [datasets/README.md](../README.md)):

```toml
datasets = ["rpg", "my-ruleset"]
```

## How to bootstrap a campaign

1. Create a Lens project and add `datasets = ["rpg"]` to `lens.toml` (plus at least one `[[llm]]` block — see [Configuration](../../docs/configuration.md)).
2. Run `lens check` to validate config and API keys.
3. Select a narrative slug:

   ```bash
   lens use my-campaign
   ```

4. Create a player character either manually or with design:
   - **Manual:** `lens kb add pc.hero` (or copy from the `pc._template` stub in the dataset), then pin at the narrative root: `lens pin kb add pc.hero`
   - **Assisted:** from the campaign root, run `lens design --module pc "Create my hero"` and finish with `lens design --end` to extract KB objects.
5. Optional: add locations, NPCs, or fronts from dataset templates (`location.*`, `npc.*`, …) the same way.
6. Open a **play** session at the cursor (first call creates a sub-node and auto-pins `rules.system` and `rules.rpg`):

   ```bash
   lens play "We reach the gate at dusk."
   ```

7. Append player lines without calling the GM, or pass the scene to the model:

   ```bash
   lens play "> I scout the wall."
   lens play --pass
   ```

8. Close the session when done: `lens play --end` (summarizes back to the parent node).

**Requirements at generation time:** at least one `pc.*` pinned on an ancestor, plus `rules.system` and `rules.rpg` (the play session pins the rules automatically). See [lens/rpg/README.md](../../lens/rpg/README.md) for modules (`--module combat`), nesting, and `--pass` behaviour.

For time passes and fronts, use `lens advance` — same session pattern as play; see the [CLI reference](../../lens/cli/README.md).

## Configuration

The RPG dataset exposes one configuration key, settable under `[config-rpg]` in the project's `lens.toml`:

| Key | Values | Default | Description |
|-----|--------|---------|-------------|
| `kb_dice_rolling` | `"disabled"`, `"expressions"`, `"implicit_d20"` | `"expressions"` | Whether dice expressions (e.g. `2d6+3`) show as a button in KB items; `implicit_d20` assumes any "+ number" text is actually a "d20 + number" expression and renders a button too (useful for D20 systems) |

Example override:

```toml
[config-rpg]
kb_dice_rolling = "disabled"
```

## Documentation

- **Operators and session flow** — [lens/rpg/README.md](../../lens/rpg/README.md) (`lens play`, modules, `--pass`, pinning `pc.*`)
- **Design goals** — [docs/rpg-design.md](../../docs/rpg-design.md)
- **CLI** — [lens play / advance](../../lens/cli/README.md) in the CLI reference

More dataset-specific guides (templates, design modules, advance calendars) will be added here over time.
