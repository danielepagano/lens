# [DESIGN MODULE]: LOCATION BUILD-OUT

Build `location.*` objects: places the story can keep coming back to. Locations are fractal — continent to region to city to room — but we only make objects for places that MATTER: places with pressure, recurrence, secrets, or a real chance of anchoring play. When invoked you will have a TASK to create or modify one or more locations; don't exceed the given mandate.

The `location._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Work with the user from there.

Before building geography, establish what this place is doing in the story:
- What scale? (a single building, a city, a region, a dungeon, all of the above)
- What's the purpose? (exploration hub, adventure site, recurring home base, in a travel route)
- What front or story thread brings the PCs here? 
    - If the player just wants to visit somewhere with no story connection, devise some possibilities based on existing fronts on why this visit may end up mattering after they get there (maybe they meet someone that can help them, or find a clue).
    - If there is not enough context (fronts, PC's), then create "quest hooks", interesting situations or problems that, if engaged with, can result in the creation a front (don't create the front or any deep quest, just the superficial situations the user may see).
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

Connect it to the live story:
- Which fronts play out here? Link via tags.
- Which NPCs are based here? They should tag back to this location.
- Any secrets? Use `ai:secret` comments.

GUIDELINES:
- Fewer locations, better described, is always better than many objects we'll forget to pin.
- If a location is only visited once and has no secrets, it probably doesn't need an object
- Parent links are REQUIRED — they're how the map works
- Sensory details > historical details. The AI needs to describe what the PCs experience, not lecture about the founding.

What this is not:
- Not a travel guide.
- Not a wiki paragraph about founding dates and dynasties.
- Not a reason to create a whole hierarchy when one strong place will do.
