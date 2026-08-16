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

## Content organization

| Directory | Contents |
|-----------|----------|
| `knowledge/pc/_template.md` | Player Character template (play surface — appearance, context, affiliations, problem-solving style; no power lists or backstory) |
| `knowledge/npc/_template.md` | NPC template (appearance, affiliations, goals, status; `ai:secret` for GM-only info) |
| `knowledge/location/_template.md` | Location template (type, scale, sensory feel, history, tensions; links to parent location via tag) |
| `knowledge/faction/_template.md` | Faction template (beliefs, methods, territory, stance toward party, plans) |
| `knowledge/front/_template.md` | Front template (problem, stakes, phases/beats, timeline anchors, resolution triggers) |
| `knowledge/encounter/_template.md` | Encounter template (situation, stakes, participants, scene rules, triggers, resolution) |
| `knowledge/lore/_template.md` | Lore template (arbitrary details about any topic; tagged to its subject, not vice versa) |
| `knowledge/timeline/_template.md` | Timeline template (calendar reference, day counter; tags ARE active fronts) |
| `knowledge/design/pc.md` | Design module: player character (splits into `pc.*` + `lore.*` with core questions) |
| `knowledge/design/npc.md` | Design module: NPC creation (recurring characters; story-service gated) |
| `knowledge/design/location.md` | Design module: location build-out (few locations, well-described; sensory > historical) |
| `knowledge/design/faction.md` | Design module: faction build-out (methods section is most important) |
| `knowledge/design/front.md` | Design module: front grooming (three-layer structure: surface, core question, twist) |
| `knowledge/design/encounter.md` | Design module: encounter design (per-situation artifacts — combat, social, negotiation, interrogation, chase, infiltration, puzzle, siege, auction, mixed; arc-aware) |
| `knowledge/design/_template.md` | What a design module must contain — chiefly the named artifact it produces |
| `knowledge/design/world.md` | Design module: world and setting (`lore.world` <500 words, directive-style) |
| `knowledge/rules/rpg.md` | Rules of Engagement — AI-GM behavioral contract (authority boundaries, gates, conduct) |
| `knowledge/rules/system.md` | System stub: Lasers & Feelings (CC BY 4.0; overridable by a higher-priority dataset) |

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

## Rules modules the model can request

This dataset registers no `[[dataset.modules]]` — its Lasers & Feelings `rules.system` is 8 KB and fits in one object. A dataset that splits its rules can register the split parts so `play` pulls one into scope itself when the scene turns, instead of the player predicting it with `--module`. Also see [lens-dnd README file](../lens-dnd/README.md#how-the-rules-reach-the-model).

## `rules.<type>`: usage rules for a KB type

`<type>._template` tells `design` how to **create** an object of that type. The counterpart is `rules.<type>`, which tells `play` how to **use** one: whenever any `<type>.*` object is pinned, `RulesCompanionTransform` adds `rules.<type>` to the crawl if it exists. That is convention only — ship `knowledge/rules/<type>.md` in a dataset and it activates, with no configuration and no code.

This is where per-type guidance belongs, rather than being repeated inside every object of that type. `lens-dnd` ships `rules.encounter`, `rules.stat`, and `rules.tracker` on this route.

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
