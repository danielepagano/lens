# [DESIGN MODULE]: LOCATION BUILD-OUT

Build `loc.*` objects — the geography the story moves through. Locations are fractal: a continent contains regions, regions contain cities, cities contain districts, districts contain buildings, buildings contain rooms. We only create objects for places that MATTER — places the PCs will return to, places with secrets, places that anchor the story.

Fetch `loc._template` first. Then work with the user.

STEP 0: STORY SERVICE CHECK
Before building geography, establish why it matters to the story:
- What front or PC story demands this location? Use `kb_get` to check active fronts.
- If the player just wants to visit somewhere with no story connection, suggest stubbing a front for it — even a minimal "something interesting should happen here" front is better than a disconnected location. Per the adventure design principles: if the PCs go somewhere, there should be a reason, and if there isn't one, make one.
- You can emit a `front.*` stub here and note it for the user to develop later via `design.front`.

STEP 1: UNDERSTAND SCOPE
Ask about:
- What scale? (a single building, a city, a region, a dungeon)
- What's the purpose? (exploration hub, adventure site, recurring home base, travel route)
- What front or story thread brings the PCs here?
- Does it connect to existing locations? Check what `loc.*` objects exist already

STEP 2: BUILD THE HIERARCHY
Every location links to its parent via tag (`loc.<parent-key>`). This creates the map graph. Work top-down:
1. If the containing location doesn't exist yet, create it first (even a stub)
2. Create the target location(s) with parent links
3. Note edges to sibling locations if relevant (roads, passages, visibility)

For a dungeon or building: rooms or areas that are distinct enough to matter get their own objects. Corridors, empty rooms, and transient spaces are narrated by `play` — they don't need objects.

For a city: districts or neighborhoods if they're distinct. Individual buildings only if they recur (the tavern headquarters, the temple, the black market).

For a region: settlements, landmarks, and travel routes. Wilderness between known points is narrated by `play`.

STEP 3: WRITE EACH LOCATION
Keep objects sensory and compact:
- What a character notices first (sights, sounds, smells)
- Social feel (who's here, what's the mood)
- Why it matters (dangers, opportunities, connections to fronts)
- Tensions or secrets (encoded if secret from the player)

DO NOT write encyclopedic descriptions. The AI will work with what you give it — a few vivid details are better than a paragraph of generic description.

STEP 4: CONNECT TO THE STORY
For each location, consider:
- Which fronts play out here? Link via tags.
- Which NPCs are based here? They should tag back to this location.
- Any encounters planned for this location? Tag them.
- Any secrets? Use `ai:secret` comments.

GUIDELINES:
- Fewer locations, better described, is always better than many stubs
- If a location is only visited once and has no secrets, it probably doesn't need an object
- Parent links are REQUIRED — they're how the map works
- Sensory details > historical details. The AI needs to describe what the PCs experience, not lecture about the founding.
