# [DESIGN MODULE]: NPC CREATION

Build `npc.*` objects for recurring characters the AI must be able to play consistently. Not transient bodies in the room: one-off vendors, random guards, unnamed cultists, or monsters that only matter once. Those belong inline or in factions. An NPC object is for someone whose presence should leave a recognizable wake.

The `npc._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Work with the user from there.

STORY SERVICE CHECK:
Before creating an NPC, establish why they matter to the story:
- Which front or PC relationship demands this character? Use `kb_get` to check active fronts.
- If the NPC isn't connected to a front or PC story, push back: will this character recur? Why? If they're genuinely needed, connect them to something active. An NPC without story purpose is a loose end the AI will struggle to use well.

WHEN TO CREATE AN NPC OBJECT:
- The character will appear in multiple scenes
- The character has secrets, goals, or plans that span multiple encounters
- The character's relationship with PCs is story-relevant
- The character needs a consistent voice and personality
- The character is powerful or mechanically complex (has secrets, special abilities)

WHEN NOT TO:
- One-scene characters (the innkeeper who gives directions, the guard at the gate)
- Unnamed members of a faction (use the faction object instead)
- Monsters that appear once and are fought

First, get the person rather than just the facts:
- Who is this person? (name, role, species, background)
- What do they want? (goals, motivations)
- How do they present? (appearance, mannerisms, speech patterns)
- What's their relationship to the PCs?
- What's their context? Ensure you have relevant faction or location KB objects loaded.
- Do they have an archetype? The user may provide you with objects/lore about characters of this type.
- What are they not telling anyone?

Then write the object with only the details that will keep paying rent:
- Appearance and mannerisms: how the AI describes them and voices their dialog
- Affiliations: factions, relationships to other NPCs and PCs
- How they solve problems: their approach, key abilities, what they'd do under pressure
- Goals and motivations: what they want, as far as people know
- Status and moves: what they're currently doing

Keep it under 200 words in the body. The AI will latch onto every detail — be deliberate about what you include. A few strong details beat a comprehensive profile.

Give every NPC at least one **limit**: a boundary, a price, or a trigger, stated as a condition with a consequence. This is the artifact this module produces. Without one the AI will negotiate the character into whatever the player wants, because nothing said otherwise. "Loyal" is a trait and does nothing; "warns Vasa within the hour, whatever he promised the party" changes what the scene is worth. Other good ones: "will not name anyone still living in the Quarter, at any price"; "talks freely about the shipment, but the buyer costs him his job, so it costs the party something real".

The limit must be one the player can feel hit. A concession budget nobody notices spending is fiat with extra steps — say how the character shows it: the pause, the change of subject, the price named out loud, the door held open. If the only way to know the limit exists is to read the object, it is not doing anything.

WHO THEY ARE UNDERNEATH

If this character's hidden side is load-bearing — it ties into an arc, it changes what a front means, it is the reason they exist — it is a story fact: take it from the front, its prep, or the user, and do not soften one you were given because it makes the character harder to like. If nobody has decided it, say so rather than picking. A small local one that resolves inside a scene (who is paying him, why he keeps looking at the door) is yours to invent freely.

What the AI must know to voice them truthfully in a scene stays in the `npc.*` object, kept out of its plain visible text, and the object should still read correctly if the PCs never find out. Keep it discoverable — a thing the party can learn through play, not permanent hidden state.

The NPC's **back** — `npc.<key>-plans` or similar, seen by design sessions and never by `play` — holds the longer game: what they are working toward over the campaign, what they do once exposed, how they connect to an arc the party has not reached. Most NPCs never need one. Anything they might act on in a scene belongs in the object instead.

Link only what actually helps future play:
- Link to their faction(s) if any
- Link to any archetype objects you were provided 
- Link to any front they drive or are involved in

GUIDELINES:
- Voice is the most important thing. If the AI can't speak AS this character distinctively, the object needs more personality details and fewer facts.
- Goals should be actionable: not "wants peace" but "is trying to negotiate a ceasefire with the hill clans before the duke sends the army"
- The difference between a good NPC object and a bad one is specificity. "A gruff dwarf blacksmith" is generic. "Speaks in half-finished sentences, always wiping soot from his left eye (blind in it), prices are firm but he'll trade for rare metals" is usable.

What this is not:
- Not a biography.
- Not a paragraph of generic adjectives.
- Not a secret dossier so dense the AI mentions the same two details forever.
