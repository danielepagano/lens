# [DESIGN MODULE]: INITIATIVE TRACKER

Build or update a `tracker.*` object: the live, clickable state of one fight — initiative order, HP, conditions, and every expendable resource each creature has. Launch it the moment initiative is rolled, from the scene, the stat blocks, and the order the player reports.

The `tracker._template` layout is included in RELEVANT KNOWLEDGE when you use this module: it carries the exact shape. This module is how you get there.

THE ARTIFACT

One tracker object per fight, containing one entry per combatant, sorted by initiative descending. It is checkable in a way most design output is not: every resource on a creature's stat block either has a counter in the tracker or does not, and `rules.tracker` tells `play` to treat this object as canonical state. A tracker that is missing a recharge ability is not a stylistic problem — it is `play` promising an ability the creature has already spent.

IMPORTANT: emit ONLY the tracker markdown in your `kb` block — no reasoning, no commentary before or after, no narration of the tool calls you made.

Always include `tags: state` in the `kb` fence when you create one. The template declares the same default, but the fence extractor does not read template front matter, so yours has to say it.

PROCEDURE

1. **Get the roster and the order.** Every combatant and its initiative count. The player rolls initiative; ask for the order if they have not given it.
2. **Load each combatant** with `kb_get`: `pc.*`, `npc.*`, and `stat.*` alike. For a PC or NPC, check its tags for a linked stat block — that link is what tells you a familiar, mount, or summon exists.
   - A PC may control extra creatures. Add them to the order after the PC unless the player gave them their own initiative. If the `pc.*` object links no stat block, there is nothing to add: do not invent a pet.
3. **Parse resources** off each stat block (below). Everything starts at full unless the story says otherwise.
4. **Write one entry per combatant** in the template's shape, sorted by initiative descending. Identical creatures get separate entries with a number appended (Bandit 1, Bandit 2), each with its own HP and resources — load the block once, write the entries twice.

READING RESOURCES OFF A STAT BLOCK

| On the block | In the tracker |
|---|---|
| `AC` | plain text in the summary, after the name — not a counter |
| `HP` | `` HP: `#max/max` `` in the summary, after AC |
| `Legendary Resistance (N/Day)` | `` Legendary Resistances Used: `#0/N` `` |
| `Legendary Action Uses: N` | `` Legendary Actions Used: `#0/N` `` (reset at start of turn) |
| `N/Day Each:` or `1/Day Each:` spell lists | a sub-bullet per spell under `- Spells Used:`, qualifiers stripped |
| any other `(N/Day)` trait | `` {Trait}: `#0/N` `` as a top-level bullet |
| `(Recharge N–M)` ability | `` {Ability}: Charged `[x]` (on N–M) `` — starts checked |
| `At Will:` spells | nothing; they cost nothing to use |
| Reactions named in the block (Parry, etc.) | nothing; the universal Reaction Used bullet covers it |

- **Strip spell qualifiers**: "Fireball (level 4 version)" → "Fireball"; "Destructive Wave (Necrotic)" → "Destructive Wave".
- **Do not double-count**: a Legendary Resistance or spell-slot line already handled above is not also an "other trait".
- **Lair**: use lair counts only when the context explicitly places the creature in its lair. "Legendary Resistance (3/Day, or 4/Day in Lair)" is 3; "Legendary Action Uses: 3 (4 in Lair)" is 3. If the lair is confirmed, note "(in lair — +1)" after the line.

UPDATING AN EXISTING TRACKER

The task will say what changed — newcomers arrived, someone left, something was recorded wrong. Preserve every existing HP value, counter, and note unless you were told to change it. A refresh that silently heals the boss is worse than no tracker.

CHECKING YOUR WORK

- Does every combatant in the fight have exactly one entry, at the right initiative?
- Does every limited ability on every stat block have a counter, and does every counter correspond to a real line on a block?
- Are PC entries free of HP and resource bullets, and monster entries free of the Active marker?
- Is the front matter the annotation form (`[` / `    kb-details: true` / `]: #`) rather than YAML `---`?
- Did anything other than tracker markdown end up in the block?

WHAT THIS IS NOT

- Not a place for stat data that is not a resource: no saves, skills, senses, actions, or damage lines.
- Not a combat log. It is current state; the fiction lives in the narrative.
- Not yours to update during play. `rules.tracker` tells `play` to read it and never write it.
