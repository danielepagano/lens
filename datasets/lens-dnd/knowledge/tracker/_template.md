[
    kb-details: true
    tags: state
]: #
<!-- D&D initiative tracker. Usage: created once initiative is rolled and updated by the player through the fight; `play` reads it as canonical state. `design.tracker` is how one gets built. -->
## Initiative Tracker: {Encounter name}

<!--
THE SHAPE

One `<details>` element per combatant, sorted by initiative count descending. The
`kb-details: true` front matter turns on master/detail view so `kb/…` links open
in a side panel; `tags: state` keeps a live object out of the cacheable prefix.

  <details><summary>{init} - [{Name}](kb/{stat|npc|pc}.{id}) | {suffix}</summary>
  - Reaction Used: `[ ]`
  {resources}

  Conditions:
  ```notes
  ```
  </details>

- **PCs**: suffix is ``Active `[x]``` (or `` `[ ]` ``). No HP, no resource bullets.
- **Monsters / NPCs**: suffix is ``AC: N | HP: `#current/max` ``. No Active marker.
  Append `(allied)` for allied stat blocks and NPCs.
- **NPC with a stat block**: link the NPC, then the block in parens —
  `[Velthor](kb/npc.velthor) ([mage](kb/stat.mage))`.
- **Reaction Used** is the first bullet of every entry, PC or not: one reaction
  per round for everyone, and the player knows what theirs are.
- **Conditions** is a ```notes``` block on every entry, left empty.

RESOURCE BULLETS (monsters and NPCs only)

  - Legendary Resistances Used: `#0/N`
  - Legendary Actions Used: `#0/N` (reset at start of turn)
  - Spells Used:  (one sub-bullet per N/Day or 1/Day Each spell, `#0/N`)
  - {Trait Name}: `#0/N`   — any other (N/Day) trait
  - {Ability Name}: Charged `[x]` (on N–M)   — any (Recharge N–M) ability, starts charged

The tracker is static: nothing updates it but the player, clicking through it as
the fight runs.
-->

<details><summary>0 - [Name](kb/stat.slug) | AC: 0 | HP: `#0/0`</summary>
- Reaction Used: `[ ]`

Conditions:
```notes
```
</details>

<details><summary>0 - [PC Name](kb/pc.slug) | Active `[x]`</summary>
- Reaction Used: `[ ]`

Conditions:
```notes
```
</details>
