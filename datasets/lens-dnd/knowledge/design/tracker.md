# [DESIGN MODULE]: INITIATIVE TRACKER

Build a `tracker.*` object: the live, per-round state of one fight — initiative order, HP, position, conditions, expended resources. Reach for this the moment initiative is rolled and the fight is big enough that memory will not hold it: several distinct creatures, legendary or recharge resources, allied NPCs, or a boss the party will grind down over many rounds.

The `tracker._template` is included in RELEVANT KNOWLEDGE when you use this module. It is the authority on the markup — entry format, what a PC entry never carries, what `[position]`/`[conditions]` look like on the line. Follow it literally; this module is about the *inputs* and the *derivation*: gathering the roster, turning a stat block into resource counters, and writing a position worth reading mid-fight.

WHAT A TRACKER IS FOR

A tracker is the one object in this system that is deliberately mutable state, and that is why it is tagged `state`: Lens renders it at the tail of the prompt, right before the task, so the player can edit it every round without invalidating the cached prefix. `rules.tracker` tells `play` how to read one — that it is canonical, that it outranks the prose, and that `play` must never try to update it.

It is correct in a very literal way: for every creature in the fight there is exactly one entry, at the right initiative, showing what it has left. If a creature is in the fiction and not in the tracker, the tracker is wrong.

BEFORE YOU BUILD

You need three things, and two of them usually have to be asked for:

- **The roster.** Take it from the pinned `encounter.*` object — its `## Prep and reference` roster is exactly this list, with counts. If no encounter is pinned, ask who is in the fight.
- **The initiative order.** The player rolled it; you cannot know it. Ask for it plainly, as a list of numbers against names. Do not invent initiative counts, and do not offer to roll them.
- **Starting condition.** Everything starts at full HP with all resources unspent unless the story already says otherwise — a creature the party softened up in a previous round, a spell already concentrated on, a boss that used its breath weapon on approach. Ask if the fight is already underway.

Then `kb_get` each `stat.*`, `npc.*`, and `pc.*` in the roster. Check `npc.*` and `pc.*` tags for linked stat blocks — a PC's familiar, mount, or summon gets its own entry only if the PC object actually links one.

DERIVING RESOURCES (per stat block, from `kb_get`)

- AC line → `AC: N` — summary, after Name, before HP (plain text, not a counter).
- HP line → `HP: `#current/max`` in summary after AC (both sides = max at start unless the story noted otherwise).
- Legendary Resistance (N/Day) → `Legendary Resistances Used: `#0/N``.
- Legendary Action Uses: N → `Legendary Actions Used: `#0/N`` (resets at the start of the creature's turn).
- N/Day Each: or 1/Day Each: (spells list) → bullet each under `- Spells Used:`, strip qualifiers (see below).
- Other (N/Day) trait (e.g. Protective Magic (3/Day)) → `Trait Name: `#0/N`` top-level bullet — don't double-count a Legendary Resistance or spell-slot line already handled above.
- (Recharge N–M) ability → `Ability Name: Charged `[x]` (on N–M)`, start checked (available at combat start).
- At Will: spells → ignore, they never run out.
- Reactions listed in the stat block (e.g. Parry) → do not track separately, covered by the universal Reaction Used checkbox.

Strip spell-name parentheticals: "Fireball (level 4 version)" → "Fireball"; "Destructive Wave (Necrotic)" → "Destructive Wave".

Only include lair counts/actions when the context explicitly says the creature is in its lair. A stat block offering "Legendary Resistance (3/Day, or 4/Day in Lair)" uses the non-lair count (3) unless lair is confirmed, in which case note it: "(in lair — +1)" after the resource line.

POSITION

`[position]` is one line of spatial and sensory awareness — where the creature is and what it can perceive right now, concise enough to read at a glance. Draw it from whichever of these the creature actually has:

- **environment** — terrain, cover, elevation, lighting, a feature it's using or threatened by
- **the party** — range or reach to whoever it's fighting, line of sight, whether it's flanked or flanking
- **senses** — darkvision, blindsight, tremorsense, keen smell or hearing extending its awareness past what a sighted human would notice

One phrase, not a paragraph — "Airborne over the lake, darkvision covers the cavern," not a tactical essay. Leave it empty only when the fiction genuinely hasn't placed the creature yet, and keep it current as the fight moves rather than letting it go stale.

SORT AND DUPLICATES

Sort entries by initiative descending. Duplicate stat blocks get an appended number (Bandit 1, Bandit 2) — load the stat block once, but create a separate entry for each, with its own HP, resources, position, and conditions.

WHAT NOT TO DO

- Do not roll anything, including initiative. The player rolls; you transcribe.
- Do not put HP, AC, or resource counters on a PC entry. The player tracks their own sheet, and duplicating it creates two truths.
- Do not paste stat block content into the tracker. It links to the block; it does not restate it.
- Do not build a tracker for a fight the player can hold in their head. Three goblins do not need one.
- Do not omit recharge abilities, include At Will spells, or keep spell-name qualifiers — see DERIVING RESOURCES above.
- Do not apply lair counts without explicit lair context.
- A tracker is a transcription job, so it is almost always the only object worth emitting. If the fight is missing an encounter, an NPC, or a stat block, say so — and build it here only if the user asked for that too, with `kb_get design.<key>` for the module that covers it.

UPDATING AN EXISTING TRACKER

If a `tracker.*` for this fight already exists, the task is a diff, not a rebuild: add newcomers at their initiative, remove the dead or fled, correct mistakes. Preserve every existing HP value, counter, position, and condition note unless the user says to reset it — those are the player's live record, and rebuilding from the stat blocks silently heals the whole encounter.
