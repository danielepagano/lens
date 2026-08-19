[
    tags: state
]: #
<!--
D&D INITIATIVE TRACKER — SHAPE ONLY. `design.tracker` covers gathering the
roster, deriving resources, and writing position; `rules.tracker` covers
reading one at the table. This file is the markup, nothing else.

A tracker is live state: always put `tags: [state]` in the kb fence itself
when creating one (this template's own front matter defaults to the same,
but the kb-fence extractor does not read that — it has to be in your block).

Every tracker opens with the master/detail annotation, so KB links inside it
open in a side panel instead of navigating away:

    [
        kb-details: true
    ]: #

Then one <details> per combatant, sorted by initiative descending:

  <details><summary>{init} - [{Name}](kb/{stat|npc|pc}.{id}) | {suffix}</summary>
  - Reaction Used: `[ ]`
  {resources}
  > [position] 
  > [conditions] 
  </details>

- **PCs** — `{suffix}` is `Active `[x]`` (or `[ ]``); no HP, no `{resources}` line. The player's own sheet owns that.
- **Monsters/NPCs** — `{suffix}` is `AC: N | HP: `#current/max``; no Active marker. Add `(allied)` for an allied stat block or NPC.
- An NPC with a stat block links both: `[Velthor](kb/npc.velthor) ([mage](kb/stat.mage))`.
- A PC's linked familiar/mount/summon gets its own entry, same shape as any other stat block.
- `{resources}` is the creature's own tracked counters and checkboxes, one bullet each — see `design.tracker` for how they're derived.
- `Reaction Used: `[ ]`` is the one line every entry has, PC and monster alike.
- `> [position] ` and `> [conditions] ` are always present, even empty — ready to fill in mid-fight.

FULL EXAMPLE:

  [
      kb-details: true
  ]: #

  ## Initiative Tracker: Test Battle

  <details><summary>20 - [Amy](kb/pc.Amy) | Active `[x]`</summary>
  - Reaction Used: `[ ]`
  > [position] 
  > [conditions] 
  </details>

  <details><summary>15 - [Goblin 1](kb/stat.goblin-warrior) | AC: 15 | HP: `#10/10`</summary>
  - Reaction Used: `[ ]`
  > [position] Behind the overturned cart, 15 ft. from Amy
  > [conditions] 
  </details>

  <details><summary>11 - [Kurmat](kb/stat.ancient-red-dragon) | AC: 22 | HP: `#507/507`</summary>
  - Reaction Used: `[ ]`
  - Legendary Resistances Used: `#0/4`
  - Spells Used:
      - Fireball: `#0/1`
      - Scrying: `#0/1`
  - Legendary Actions Used: `#0/3`
  - Fire Breath: Charged `[x]` (on 5–6)
  > [position] Airborne over the lake, darkvision covers the whole cavern
  > [conditions] 
  </details>

COMMON MISTAKES (shape — see `design.tracker` for the rest):
- Writing `kb-details` as YAML (`---`) inside the body — it must be the annotation form, `[\n    kb-details: true\n]: #`. The kb fence's own `---` front matter still carries `id` and `tags: [state]` as usual.
- Adding HP or resources to a PC entry.
- Adding an Active `[x]`/`[ ]` marker to a monster/NPC entry.
- Including non-resource stat data (AC beyond the summary line, saves, skills, senses, actions, damage) — the entry links the stat block, it does not restate it.
-->
[
    kb-details: true
]: #

## Initiative Tracker: Template

<details><summary>0 - [Name](kb/stat.slug) | AC: 0 | HP: `#0/0`</summary>
- Reaction Used: `[ ]`
> [position] 
> [conditions] 
</details>
