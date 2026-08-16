# [DESIGN MODULE]: FACTION BUILD-OUT

Build `faction.*` objects: how a group behaves as a group, so the AI can run its unnamed members. Use when a group will recur, drives or opposes a front, or shows up in encounters as more than one body.

A faction is not just "an organization in the setting." It is any group whose shared goals, methods, or resources create pressure: a thieves' guild, a regiment, a merchant cartel, a wolf pack defending territory, a neighborhood watch, a cult of three. If the PC party acquires collective goals, assets, methods, or allies, they become a faction too.

Factions serve two practical purposes during play:
1. **Contextualizing fronts**: a front often has a faction driving it or opposing it. The faction object tells the AI *how* that group pursues its goals — methods, resources, attitude — so the front's escalation feels grounded.
2. **Controlling groups of characters**: when an encounter involves a group (bandits, cultists, guards, a merchant consortium), the faction object tells the AI how those individuals behave *as a group* — who fights, who flees, who negotiates, what they'd never do. This replaces the need for individual NPC objects for unnamed members.

A faction can be very brief. If all you need is "these goblins are territorial and fight dirty," that's a valid faction object. Not every faction needs a political manifesto.

The `faction._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Work with the user from there.

Before creating a faction, establish why this group needs persistence:
- Which front does this faction drive, oppose, or complicate? Use `kb_get` to check active fronts.
- Which PCs interact with this faction? Are any members? Do any have history with it?
- If the faction isn't connected to a front or PC story, push back: will this group recur? Will encounters involve its members? If it won't appear again, just describe the group inline in the encounter or narrative — no object needed.

Understand the group as a group:
- Who are they? (name, type of group, size and reach)
- What do they want? (collective goals — not individual member goals)
- How do they operate? (methods, code of conduct, tactics, brutality or subtlety)
- Where are they strongest? (territory, sphere of influence, resources)
- Who do they recruit, and who do they reject? (hard rules for membership — these constrain the AI during play)
- How do they feel about the PCs and other known factions? (alliances, rivalries, indifference)
- What are they doing right now? (ongoing plans or operations)

Not all of these need answers. A pack of dire wolves needs territory, tactics, and maybe a leader — not a recruitment policy. Scale the object to the faction's narrative weight.

Write the object so unnamed members become easy to run. Keep it compact. A faction object should be **under 200 words** in the body. The AI will use every detail you give it to control group behavior, so be deliberate:
- Identity and beliefs: one or two sentences on who they are and what drives them
- Methods: how they solve problems. The most important section, because it directly controls how the AI plays unnamed members. Write these as rules that **decide** behaviour mid-scene without further thought — "they break when they lose a third of their number, and they take their wounded"; "never violence in daylight, never in front of a witness who can name them". "Ruthless but disciplined" is a description and decides nothing.
- Reach and recruitment: where they operate, who joins, hard constraints
- Stance toward PCs and other factions: current relationship, not history
- Current operations: what they're actively doing, as far as anyone knows

If the faction is minimal (a type of creature, a loose gang), you can skip sections that don't apply. A wolf pack doesn't need "beliefs" — it needs territory, pack tactics, and what provokes or deters them.

If the faction has hidden agendas, internal conflicts, or information the players shouldn't know:
- Use `ai:secret` comments for information only the AI should see
- The visible text should read naturally without the secret — faction names may appear in pin lists the player can see
- Secrets should be discoverable through play (infiltration, interrogation, observation)

Link with restraint:
- Tag the faction with its headquarters `location.*` if one exists
- Tag with the faction leader's `npc.*` or `pc.*` if they have an object
- Do NOT tag fronts from the faction — fronts tag back to the faction instead
- If the faction has named members with `npc.*` objects, those NPCs tag back to the faction — not the other way around

If the party has evolved to have collective goals, shared assets, a reputation, or methods:
- Create `faction.party` (or a more specific name if they've named themselves)
- Tag each `pc.*` to this faction
- Keep it focused on what the party does *as a group* — not a summary of individual characters
- This object is useful when NPCs or other factions react to the party's reputation, or when the AI needs to understand how the group operates together
- Update it as the party's goals and methods evolve

GUIDELINES:
- Factions are about *collective behavior*, not organizational charts. The AI needs to know how members act, not the faction's founding history.
- A faction that only appears in one encounter probably doesn't need an object — describe the group in the encounter instead.
- If a faction needs named NPCs (a leader, a contact, a rival within the group), suggest loading the NPC design module. Do not create NPC objects yourself.
- If a faction needs a headquarters or territory location, suggest loading the location design module. Do not create location objects yourself.
- Check existing objects before creating. Use `kb_get` and `kb_with_tag` to find factions that might already cover this group or overlap with it.
- Remember, if you are in `advance` mode you should work more quickly, focusing on incremental changes only, and be done in one shot; do not ask for follow-up tasks or questions unless absolutely necessary.

What this is not:
- Not an organizational chart.
- Not founding history unless it changes present behavior.
- Not a named-NPC substitute when what you really need is a person.
