# [DESIGN MODULE]: INITIATIVE TRACKER

Build a `tracker.*` object: the live, per-round state of one fight — initiative order, HP, conditions, expended resources. Reach for this the moment initiative is rolled and the fight is big enough that memory will not hold it: several distinct creatures, legendary or recharge resources, allied NPCs, or a boss the party will grind down over many rounds.

The `tracker._template` is included in RELEVANT KNOWLEDGE when you use this module. It is the authority on the exact shape — entry format, which resources become counters, what never appears on a PC entry. Follow it literally; this module is about getting the *inputs* right, not the markup.

WHAT THE ARTIFACT IS

A tracker is the one object in this system that is deliberately mutable state, and that is why it is tagged `state`: Lens renders it at the tail of the prompt, right before the task, so the player can edit it every round without invalidating the cached prefix. `rules.tracker` tells `play` how to read one — that it is canonical, that it outranks the prose, and that `play` must never try to update it.

So the artifact is checkable in a very literal way: for every creature in the fight there is exactly one entry, at the right initiative, showing what it has left. If a creature is in the fiction and not in the tracker, the tracker is wrong.

BEFORE YOU BUILD

You need three things, and two of them usually have to be asked for:

- **The roster.** Take it from the pinned `encounter.*` object — its `## Prep and reference` roster is exactly this list, with counts. If no encounter is pinned, ask who is in the fight.
- **The initiative order.** The player rolled it; you cannot know it. Ask for it plainly, as a list of numbers against names. Do not invent initiative counts, and do not offer to roll them.
- **Starting condition.** Everything starts at full HP with all resources unspent unless the story already says otherwise — a creature the party softened up in a previous round, a spell already concentrated on, a boss that used its breath weapon on approach. Ask if the fight is already underway.

Then `kb_get` each `stat.*`, `npc.*`, and `pc.*` in the roster. Check `npc.*` and `pc.*` tags for linked stat blocks — a PC's familiar, mount, or summon gets its own entry only if the PC object actually links one.

WHAT NOT TO DO

- Do not roll anything, including initiative. The player rolls; you transcribe.
- Do not put HP, AC, or resource counters on a PC entry. The player tracks their own sheet, and duplicating it creates two truths.
- Do not paste stat block content into the tracker. It links to the block; it does not restate it.
- Do not build a tracker for a fight the player can hold in their head. Three goblins do not need one.
- Do not emit KB objects for anything but the tracker. If the fight needs an encounter, an NPC, or a stat block that does not exist, say so and let the user load the module for it.

UPDATING AN EXISTING TRACKER

If a `tracker.*` for this fight already exists, the task is a diff, not a rebuild: add newcomers at their initiative, remove the dead or fled, correct mistakes. Preserve every existing HP value, counter, and condition note unless the user says to reset it — those are the player's live record, and rebuilding from the stat blocks silently heals the whole encounter.
