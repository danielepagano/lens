[
    tags: state
]: #
<!--
D&D INITIATIVE TRACKER
The shape of a live combat tracker: initiative order, HP, conditions, expended resources. Follow when writing or updating a `tracker.*` object; `design.tracker` covers gathering the roster and `rules.tracker` covers reading one at the table.

IMPORTANT: Emit ONLY the final tracker markdown — no reasoning, no commentary before or after, no commentary about making tool calls. The content below (after this comment block) is the tracker starter. Replace the placeholder comments with the actual data as you build the full tracker with all combatants.

A tracker is live state, updated every round: always include `tags: [state]` in the kb fence when creating one (this template's own front matter declares the same default, applied automatically if the object is created outside the design flow — but the kb-fence extractor does not read it, so put it in your own block).

Every combatant is a <details> element sorted by initiative count (descending). PCs get an Active [x]/[ ] marker, reaction tracker, and a conditions textarea only. Monsters/NPCs get AC, HP, resource/condition bullets, and a conditions textarea.

Start every tracker with:

    [
        kb-details: true
    ]: #

ENTRY FORMAT

  <details><summary>{init} - [{Name}](kb/{stat|npc|pc}.{id}) | {suffix}</summary>
  - Reaction Used: `[ ]`
  {resources}

  Conditions:
  ```notes
  ```
  </details>

  - PCs: suffix is `Active `[x]`` (or `[ ]`). No HP, no resource bullets.
  - Monsters/NPCs: suffix is `AC: N | HP: `#current/max``. No Active marker. Add `(allied)` for allied pc-allied stat blocks and NPC's.
  - NPC with a stat block: link the NPC and append the stat block (which is a tag on the npc object) in parens, e.g. [Velthor](kb/npc.velthor) ([mage](kb/stat.mage))
  - Some PC's may control additional stat blocks: familiars, mounts, summons, etc. Use kb_get to see if the pc has any stat blocks links, and add them to the initiative after the PC (or at a rolled initiative is specified). If the pc KB object does NOT link a stat block, do not include it! 

UNIVERSAL (every entry, no parsing needed):
  - `Reaction Used: `[ ]`` — first bullet inside every entry. Every creature gets one reaction per round. This is just a reminder checkbox; the user knows what their reactions are.

RESOURCES (per stat block, read via kb_get)

   - AC line →  AC: N — add to summary after Name but before HP (plain text, not an editable counter)
   - HP line →  `HP: `#current/max`` in summary after AC (both sides = max at start unless the story noted otherwise)
  - Legendary Resistance (N/Day) →  `Legendary Resistances Used: `#0/N``
  - Legendary Action Uses: N →  `Legendary Actions Used: `#0/N`` (reset at start of turn)
  - N/Day Each: or 1/Day Each: (spells list) → bullet each under `- Spells Used:`, strip qualifiers
  - Other (N/Day) trait (e.g. Protective Magic (3/Day)) →  `Trait Name: `#0/N`` top-level bullet. Be careful not to double-count Legendary Resistance or spell-slot lines already handled above.
  - (Recharge N–M) ability →  `Ability Name: Charged `[x]` (on N–M)`, start checked (available at combat start)
  - At Will: spells → ignore
  - Reactions listed in stat blocks (e.g. Parry) → do NOT track separately — covered by the universal Reaction Used checkbox

SPELL NAME QUALIFIERS: strip parentheticals (e.g. "Fireball (level 4 version)" → "Fireball"; "Destructive Wave (Necrotic)" → "Destructive Wave").

LAIR: only include lair counts/actions if the context explicitly says the creature is in its lair. When a stat block says "Legendary Resistance (3/Day, or 4/Day in Lair)", use only the non-lair count (3). When it says "Legendary Action Uses: 3 (4 in Lair)", use only 3. If lair is confirmed, add a note like "(in lair — +1)" after the resource line.

SORT: by initiative descending. Duplicate stat blocks → append number (Bandit 1, Bandit 2). Load the stat block once but create separate entries, each with own HP/resources tracker.

STATIC: tracker does not auto-update — the player expands sections and clicks controls as they go.

PROCEDURE:
  1. Identify all participating combatants and their initiative rolls.
  2. For each pc, npc, and stat block, use `kb_get` to load its full text. For pc/npc, check its tags for any linked stat blocks.
  3. Parse each stat block for resources (see RESOURCES above). All start at max/full HP unless the story noted otherwise.
  4. Create a <details> entry per combatant using the ENTRY FORMAT above.
  5. Sort entries by initiative descending. For duplicates, append a number (Bandit 1, Bandit 2).
  6. The tracker is static — the player expands sections and clicks controls as they go.

FULL EXAMPLE (for reference — a completed tracker with multiple entries):

  [
      kb-details: true
  ]: #

  ## Initiative Tracker: Test Battle

  <details><summary>20 - [Amy](kb/pc.Amy) | Active `[x]`</summary>
  - Reaction Used `[ ]`  

  Conditions:
  ```notes
  ```
  </details>

  <details><summary>15 - [Goblin 1](kb/stat.goblin-warrior) | AC: 15 | HP: `#10/10`</summary>
  - Reaction Used `[ ]`  

  Conditions:
  ```notes
  ```
  </details>

  <details><summary>14 - [Bob](kb/pc.Bob) | Active `[x]`</summary>
  -  Reaction Used `[ ]`  

  Conditions:
  ```notes
  ```
  </details>

  <details><summary>11 - [Kurmat](kb/stat.ancient-red-dragon) | AC: 22 | HP: `#507/507`</summary>
  - Reaction Used `[ ]`  
  - Legendary Resistances Used: `#0/4`
  - Spells Used:
      - Fireball: `#0/1`
      - Scrying: `#0/1`
  - Legendary Actions Used: `#0/3` (reset at start of turn)
  - Fire Breath: Charged `[x]` (on 5–6)

  Conditions:
  ```notes
  ```
  </details>

  <details><summary>10 - [Velthor](kb/npc.velthor) ([mage](kb/stat.mage)) (allied) | AC: 12 | HP: `#81/81`</summary>
  - Reaction Used `[ ]`  
  - Spells Used:
      - Fireball: `#0/2`
      - Invisibility: `#0/2`
      - Fly: `#0/1`
      - Cone of Cold: `#0/1`
  - Protective Magic: `#0/3`

  Conditions:
  ```notes
  ```
  </details>

The `kb-details: true` frontmatter enables master/detail view so KB links open in a detail panel under the main content.

IF TRACKER EXISTS: task instructions say what to do (add newcomers, remove combatants, fix mistakes). Preserve existing HP/counters/notes unless told otherwise.

COMMON MISTAKES:
- Using YAML frontmatter (`---`) — must be `[\n    kb-details: true\n]: #`.
- Omitting recharge abilities.
- Including At Will: spells.
- Adding HP or resources to PCs.
- Adding Active [x]/[ ] to monster entries.
- Lair counts without explicit lair context.
- Keeping spell qualifiers.
- Including non-resource stat data (AC, saves, skills, senses, actions, damage).
-->
[
    kb-details: true
]: #

## Initiative Tracker: Template

<details><summary>0 - [Name](kb/stat.slug) | AC: 0 | HP: `#0/0`</summary>
- Reaction Used: `[ ]`

Conditions:
```notes
```
</details>
