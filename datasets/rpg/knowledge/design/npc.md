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
- Any secrets?

Then write the object with only the details that will keep paying rent:
- Appearance and mannerisms: how the AI describes them and voices their dialog
- Affiliations: factions, relationships to other NPCs and PCs
- How they solve problems: their approach, key abilities, what they'd do under pressure
- Goals and motivations: what they want, as far as people know
- Status and moves: what they're currently doing

Keep it under 200 words in the body. The AI will latch onto every detail — be deliberate about what you include. A few strong details beat a comprehensive profile.

If the NPC has secrets:
- Use `ai:secret` comments for information only the AI should know
- The visible text should read naturally without the secret
- Secrets should be revealable through play — they're not permanent hidden state, they're things the PCs can discover

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
