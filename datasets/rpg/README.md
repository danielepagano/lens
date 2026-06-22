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

4. Create one or more **player characters** either manually or with design:
   - **Manual:** `lens kb add pc.hero` (or copy from the `pc._template` stub in the dataset), then pin at the narrative root: `lens pin kb add pc.hero`
   - **Assisted:** from the campaign root, run `lens design --module pc "Create..."` and finish with `lens design --end` to extract KB objects.
5. Create a **timeline** to track the calendar and active pressures:

   ```bash
   lens kb add timeline.epic -t
   ```

   Pin it at your narrative root with the `+` suffix so its tagged fronts follow automatically:

   ```bash
   lens pin kb add timeline.epic+     # + expands tagged fronts into context
   ```

   See [Timeline + fronts lifecycle](#timeline--fronts-lifecycle) below for how this works.

6. Add locations, NPCs, or fronts from dataset templates (`location.*`, `npc.*`, …) the same way. Initial fronts can be created with `lens design --module front`.

7. Open a **play** session at the cursor (first call creates a sub-node and auto-pins `rules.system` and `rules.rpg`):

   ```bash
   lens play "We reach the gate at dusk."
   ```

8. Append player lines without calling the GM, or pass the scene to the model:

   ```bash
   lens play "> I scout the wall."
   lens play --pass
   ```

9. Close the session when done: `lens play --end` (summarizes back to the parent node).

## Timeline + fronts lifecycle

A timeline tracks the calendar and holds tags that determine which fronts are active.
This is the backbone of your campaign's pressure system.

**Two operators split the work**:

| Operator | What it does |
|----------|-------------|
| `lens advance` | Moves the calendar, updates front content (clocks, phases, timers), rolls for random events; if does not create or retire fronts
| `lens design --module front` | Creates new fronts, closes resolved ones, manages the active fronts in the timeline

**The loop**: play → call advance when you go to sleep (fronts evolve, time passes) → play → advance → ... → design (close resolved fronts, create the next pressure) → play → advance → ...

When a front reaches resolution, advance notes it in the summary but does NOT close it. You run `lens design --module front` to close the front (removes its tag from the timeline) and design the next pressure while the resolved front is still in context. This keeps one thread behind the scenes while the next one develops.

See [docs/rpg-design.md](../../docs/rpg-design.md) for the full design rationale.

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
