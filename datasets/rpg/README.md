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
| `knowledge/npc/_template.md` | NPC template (appearance, affiliations, goals, status, and the limit that decides behaviour mid-scene) |
| `knowledge/location/_template.md` | Location template (type, scale, sensory feel, history, tensions; links to parent location via tag) |
| `knowledge/faction/_template.md` | Faction template (beliefs, methods, territory, stance toward party, plans) |
| `knowledge/front/_template.md` | Front template (problem, stakes, phases/beats, timeline anchors, resolution triggers) |
| `knowledge/encounter/_template.md` | Encounter template (situation, stakes, participants, scene rules, triggers, resolution) |
| `knowledge/lore/_template.md` | Lore template (arbitrary details about any topic; tagged to its subject, not vice versa) |
| `knowledge/timeline/_template.md` | Timeline template (calendar reference, day counter; tags ARE active fronts) |
| `knowledge/design/planning.md` | Design module: story planning (setting frame, arcs, core questions, twists; produces material, not artifacts) |
| `knowledge/design/pc.md` | Design module: player character (splits into `pc.*` + `lore.*` with core questions) |
| `knowledge/design/npc.md` | Design module: NPC creation (recurring characters; story-service gated) |
| `knowledge/design/location.md` | Design module: location build-out (few locations, well-described; sensory > historical) |
| `knowledge/design/faction.md` | Design module: faction build-out (methods section is most important) |
| `knowledge/design/front.md` | Design module: front grooming (schedules prepared pressure; makes each front move on its own) |
| `knowledge/design/encounter.md` | Design module: encounter design (any prepared situation; scene rules quoted or invented, deltas only; arc-aware) |
| `knowledge/design/_template.md` | What a design module must contain — chiefly the named artifact it produces for play to act on |
| `knowledge/rules/advance.md` | Operator module for `advance`: what a time step moves, what it must not, how to read a count/phase/chance rule |
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

6. Work out what the story is about before building anything to play: `lens design --module planning`. That session produces material — the setting frame, the arcs, the buried questions — not artifacts. Skip it only if you already have that material, from your own notes or from a published adventure.

7. Add locations, NPCs, or fronts from dataset templates (`location.*`, `npc.*`, …) the same way. Initial fronts can be created with `lens design --module front`, which schedules and mechanises the material from step 6 rather than inventing new story.

8. Open a **play** session at the cursor (first call creates a sub-node and auto-pins `rules.system` and `rules.rpg`):

   ```bash
   lens play "We reach the gate at dusk."
   ```

9. Append player lines without calling the GM, or pass the scene to the model:

   ```bash
   lens play "> I scout the wall."
   lens play --pass
   ```

10. Close the session when done: `lens play --end` (summarizes back to the parent node).

## Timeline + fronts lifecycle

A timeline tracks the calendar and holds tags that determine which fronts are active.
This is the backbone of your campaign's pressure system.

**Two operators split the work**:

| Operator | What it does |
|----------|-------------|
| `lens advance` | Moves the calendar and everything waiting on it — front clocks and phases, trackers, any object whose body states a time cost — and promotes the next prepared piece from a `-prep` facet. It invents nothing, and creates or retires nothing
| `lens design --module front` | Creates new fronts, closes resolved ones, manages the active fronts in the timeline

**The loop**: play → call advance when you go to sleep (fronts evolve, time passes) → play → advance → ... → design (close resolved fronts, create the next pressure) → play → advance → ...

When a front reaches resolution, advance notes it in the summary but does NOT close it. You run `lens design --module front` to close the front (removes its tag from the timeline) and design the next pressure while the resolved front is still in context. This keeps one thread behind the scenes while the next one develops.

See [docs/rpg-design.md](../../docs/rpg-design.md) for the full design rationale.

## Prep material and the `-` facet

An object may have a **back**: a same-type object whose key is the object's key plus a `-` suffix. `front.harbour-prep`, `pc.amy-background`, `lore.world-plots`. `design` and `advance` expand the facets of every root pin automatically; `play` never does. So the front object a GM reads is the play surface, and everything the arc knows but the table must not is one id away, with no tagging and no pinning to remember.

`design --module planning` writes into the back. `design --module front` and `advance` read from it and promote pieces of it forward. Nothing enforces this — a facet is an ordinary KB object, so `@front.harbour-prep` in a play prompt still works when you want a deliberate reveal.

One caveat: expansion covers **pinned** objects only. Fronts reach context through `timeline.<id>+`, not as pins, so their prep does not ride along and the operator fetches it (`kb_with_tag ["front"]`). See the *Known gap* note in the design doc.

Full rationale: [docs/rpg-design.md](../../docs/rpg-design.md#the-play-surface-and-the-prep-surface).

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
