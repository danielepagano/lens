<!-- Design workflow: Adventure build-out. Pin this to create fronts with linked NPCs, factions, locations, and encounters. -->
ADVENTURE BUILD-OUT

Build the "what happens next" for an ongoing game. This creates or updates `front.*` objects and their supporting cast of NPCs, factions, locations, and encounter objects. This is the primary way to prepare content between play sessions.

Fetch `front._template` first. Then work with the user.

STEP 1: ASSESS CURRENT STATE
Before creating anything, understand where the game is:
- What has happened recently in the narrative? (read the pinned context)
- What fronts already exist? (`kb_with_tag` for fronts, or check what's pinned)
- What loose threads exist? (promises made, enemies escaped, mysteries unresolved)
- What does the player want to explore next?

STEP 2: BUILD OR UPDATE FRONTS
A front is a changing situation — a threat in motion, a clock ticking, a plan unfolding. Good fronts:
- Have clear stakes (what happens if the PCs do nothing)
- Have phases or beats (how it escalates)
- Connect to existing objects (factions driving it, NPCs involved, locations affected)
- Are compact enough to pin during play

For existing fronts: update to reflect what's happened. Advance the clock, change the phase, note what the PCs have done.
For new fronts: create from a hook — something the narrative has established or the player wants to introduce.

STEP 3: BUILD SUPPORTING OBJECTS
Each front may need:
- `npc.*` for key characters driving or affected by the front
- `faction.*` for groups with stakes in the outcome
- `loc.*` for places where the front plays out
- `encounter.*` for prepared scenes the front will produce

Check existing objects before creating new ones. Link everything: NPCs to factions, locations to parent locations, fronts to their driving NPC or faction.

STEP 4: PREPARE ENCOUNTERS
For each front, think about what scenes it produces. Not every scene needs a prepared encounter — `play` handles routine interactions fine with just pinned NPCs and locations. Prepare encounters for:
- Scenes with stakes and complexity (combat, tense negotiations, chases)
- Scenes with secrets (the encounter knows something the player doesn't)
- Scenes where the AI needs specific mechanical guidance (environmental hazards, puzzle rules)
- Set-piece moments the player is looking forward to

STEP 5: REVIEW AND CONNECT
Before closing:
- List all objects created/updated
- Verify links and tags are consistent
- Check that each front has enough supporting objects for play to work
- Suggest a narrative sequence: what order might these scenes unfold in?
- Note any objects that should be pinned when specific fronts become active

GUIDELINES:
- Fronts should be 2–4 at any time. More than that fragments attention.
- Not every NPC needs an object. One-off guards, vendors, bystanders are narrated by `play` from context.
- Encounters don't need to be exhaustive. A short encounter object is better than none — it gives `play` direction even if the details are sparse.
- Let the player drive what to build. Don't create content they haven't asked for or that doesn't connect to active fronts.
