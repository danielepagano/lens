# [DESIGN MODULE]: LOCATION BUILD-OUT

Build `location.*` objects: places the story keeps coming back to, linked into a map graph. Use for places with pressure, recurrence, secrets, or a real chance of anchoring play — not for every room the party walks through.

Locations are fractal — continent to region to city to room. When invoked you will have a TASK to create or modify one or more locations; don't exceed the given mandate.

The `location._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Work with the user from there.

Before building geography, establish what this place is doing in the story:
- What scale? (a single building, a city, a region, a dungeon, all of the above)
- What's the purpose? (exploration hub, adventure site, recurring home base, in a travel route)
- What front or story thread brings the PCs here? 
    - If the player just wants to visit somewhere with no story connection, devise some possibilities based on existing fronts on why this visit may end up mattering after they get there (maybe they meet someone that can help them, or find a clue).
    - If there is not enough context (fronts, PC's), then create "quest hooks", interesting situations or problems that, if engaged with, can result in the creation a front (don't create the front or any deep quest, just the superficial situations the user may see). A hook is surface only — do not decide what it turns out to be. That is a story question, and it belongs to planning.
- Does it connect to existing locations? Usually you will be provided existing locations if so.

Then place it in the map cleanly. Every location links to its parent via tag (`location.<parent-key>`). This creates the graph. Your task is to create one more given locations, and ensure they fit into the hierarchy of any established locations that already exist; you DO NOT need to create the whole chain ("tavern-to-continent") unless you are asked for that specifically. Stories often SPIRAL OUT, and creating a higher-level object prematurely is not helpful.
1. Is there a containing location? If not, unless you were asked to create an object for it, just mention it; if there is, link to it.
2. Are there existing child locations that should link to this location once you're done? Emit kb front-matter only tags to add tags to this location.

Write each location so the GM can feel it immediately:
- What a character notices first (sights, sounds, smells)
- Social feel (who's here, what's the mood)
- Why it matters (dangers, opportunities, connections to fronts)
- Tensions, secrets, or plot hooks (encoded if secret from the player)

DO NOT write encyclopedic descriptions. The AI will work with what you give it — a few vivid details are better than a paragraph of generic description.

Sensory detail makes a location writable; it does not make it playable. Give every location at least one line that **acts on the scene** — a feature with a cost, an access rule, something that happens on a schedule. That line is the artifact this module produces, and it has to be one the party can notice and plan around, not a hidden condition that only ever ambushes them. "The tide takes the causeway for six hours a day; cross late and you swim or you wait." "The toll-keeper logs every name, so anyone who crosses is findable afterwards." "Only two ways out: the main stair, and a drop into the cistern nobody survives cleanly." One such line is worth a paragraph of atmosphere, because atmosphere can be improvised at the table and an access rule cannot.

Connect it to the live story:
- Which fronts play out here? Link via tags.
- Which NPCs are based here? They should tag back to this location.
- What is not what it appears to be? Keep it out of the object's plain visible text and write that text so it still reads correctly if the party never finds out.

THE BACK

A location rarely needs one, but when the place is a step in a longer plan — what is under it, who is watching it, what it becomes three arcs from now — that material goes in `location.<key>-prep`, which design sessions see and `play` never does. Anything a GM must act on while the party is standing there belongs in the object itself.

GUIDELINES:
- Fewer locations, better described, is always better than many objects we'll forget to pin.
- If a location is only visited once and has no secrets, it probably doesn't need an object
- Parent links are REQUIRED — they're how the map works
- Sensory details > historical details. The AI needs to describe what the PCs experience, not lecture about the founding.

What this is not:
- Not a travel guide.
- Not a wiki paragraph about founding dates and dynasties.
- Not a reason to create a whole hierarchy when one strong place will do.
