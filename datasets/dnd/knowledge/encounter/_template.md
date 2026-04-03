<!-- D&D: prepared situation for play. Pin when the scene starts. Combat uses stat.* blocks and Prep roster below. -->
Encounter name

## Situation

- **Situation**: (what's happening — where, when, who is present — one or two tight paragraphs or short bullets)
- **Stakes**: (what can go wrong, what's at risk)
- **Initial positions**: (for combat/physical encounters: starting distances between groups in feet, formations, terrain zones, cover, elevation, chokepoints — enough for theater-of-mind)
- **Scene rules**: (terrain, light, hazards, time pressure, social dynamics — keep short; link `location.*` if detail is large)
- **Triggers**: (dialog escalates, timer, reinforcements, secret surfaces, phase change)
- **Resolution**: (how it can end — fronts, attitudes, loot, intel)

## Running non-PC characters

The player runs the table: initiative, rolls, and PC actions follow their rules and sheets. The AI does not roll for the player.

For each non-PC (monsters, allied stat blocks, crowds, etc.), the player asks when they care (e.g. "What does the ghast do?"). The AI answers with concrete action grounded in that **`stat.*`** or **`npc.*`** — not simulating dice unless the player asks for a suggested roll.

Add encounter-specific notes only: checks, puzzle solution secrets, priorities, group tactics, flee thresholds, spotlight beats, etc.

## Prep and reference

Include this section for combat encounters only. **`stat.*` only — use `KB['stat.…']` only in this section.** List every stat block in play with counts. Use the same **`KB['stat.key']`** header form as pinned knowledge in context. Do not paste or paraphrase stat rules here. Every **`stat.*`** listed here should also be present as a tag on the encounter object so `encounter.*+` expands to the real combatants at play time.

Example:

```
- 5× KB['stat.skeleton']
- 1× KB['stat.ghast']
```

Subheadings (**Enemies** / **Allies**) optional. Repeat a **`KB['stat.*']`** on another line if roles differ (e.g. leader vs minions).

Do **not** add **`KB['pc.…']`**, **`KB['npc.…']`**, **`KB['faction.…']`**, etc. Refer to those by name or dot-ids in Situation and Running.

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag with location, front, npc, faction as appropriate. Combat: difficulty:low/moderate/high, plus every `stat.*` used in Prep. Note: `rules.encounter` auto-pins when any encounter is in play context; tag other `rules.*` only if the scene depends on specialized procedures (e.g. `rules.chase`). -->
