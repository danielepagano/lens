# [DESIGN MODULE]: ENCOUNTER DESIGN

Build `encounter.*` objects — prepared situations for play to use as scripts. An encounter is ANY prepared situation with stakes, not just combat. A conversation with a nervous informant, a chase through a burning market, a courtroom trial, a puzzle door, a boss fight — these are all encounters.

The `encounter._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Work with the user from there.

STEP 0: STORY SERVICE CHECK
Before building anything, establish the connection to the story:
- What front does this encounter serve? Use `kb_get` to fetch the front and understand its stakes (unless it was already provided).
- Which PCs does it challenge? Check their `lore.<name>` objects for core questions this scene could pressure.
- If the encounter doesn't connect to an active front or PC story, reflect: why does this scene matter? You may propose a front for whatever tension drives the scene; if the user wants to actually create the front, they will engage with a front design module; your job is still to create the encounter.

1: UNDERSTAND THE SITUATION
Ask about:
- What's the scene? (where, when, who's involved)
- What type of situation? (combat, social, chase, puzzle, exploration, or a mix)
- What's at stake? (consequences of success and failure)
- Any secrets? (information the player shouldn't see until revealed through play)

2: ASSEMBLE PARTICIPANTS
Participants include any given PC's, plus:
- Named NPCs (recurring non-player characters) have `npc.*` objects
- Factions, both as context and to control the rules of of groups of creatures have `faction.*` objects
- Locations: if the encouter occurs is a specific, sufficiently complex, and recurring location, it will have a `location.*` object.

IMPORTANT: if you think you are missing objects, DO NOT just creat them! There are specialized Design Modules for each of these. Suggest to the user that you want to introduce an NPC, faction, or location, and have them decide whether to accept and load the appropriate module for the task. If they decline, just add necessary character and location details in the encounter itself, not other objects.  

3: COMBAT BALANCING (if applicable)
If the encounter includes combat:
- Ensure you understand how combat works; `kb_get` the `rules.system` object if you don't already have it.
- Identify participant power levels from pinned `pc.*` objects (check tags like `level:N`)
- The system may include pre-made enemies, check for a `stats._template` object for details and useful tags, then use `kb_with_tag` to find stat block candidates by type, habitat, or other relevant tags
- Rank candidates by narrative fit (a goblin ambush wants goblins, not random level-appropriate monsters)
- If the game system provides a balancing tool like `balance_encounter`, it will be visible to you; use it to generate proposals; otherwise use the game rules and GM judgment to match challenge to party capability
- Include any selected stat block links in the encounter object

4: WRITE THE ENCOUNTER OBJECT
The encounter object should be compact. It's a script, not a novel:
- Situation: one or two sentences
- Stakes: what can go wrong
- Participants: links or inline descriptions of npc/faction/stat objects
- Scene rules: special mechanics.
- Triggers: what causes shifts (dialog to combat, timer expires, reinforcements, secret revealed)
- Resolution: how it ends and what changes

5: SECRETS
If the encounter has secrets (the informant is actually a trap, the merchant is poisoning the drinks, the "abandoned" tower has invisible watchers):
- Encode secrets using the `ai:secret` comment format so only the AI sees them during play
- The encounter object's visible text should read naturally without the secret — the player may glimpse object names in pin lists

APPENDIX - ENCOUNTER TYPES
These are guidelines for scene rules, not separate templates or rigid categories:

**Combat**: Link stat blocks or create mechanically interesting adversaries. Note terrain features, environmental hazards, and enemy goals (not just "attack"). Enemies have motivations — bandits flee when losing, cultists sacrifice themselves, intelligent foes adapt.

**Social**: Note each NPC's goals, what they know, what they'll share freely, and what requires checks. Conversation encounters don't need rolls for every exchange — only when the PC pushes past what the NPC would naturally give.

**Chase/Escape**: Note starting distance, terrain type, potential complications, exhaustion rules. What ends the chase (distance, hiding, obstacle, confrontation)?

**Puzzle/Exploration**: Note the puzzle mechanics, what information is available, what checks reveal. What happens if they get stuck? What happens if they brute-force it?

**Mixed**: Most interesting encounters are mixed. Note the triggers that shift between types. A negotiation that could become a fight. A combat that the quarry flees from. A puzzle room with a guardian. Write the triggers explicitly.

ARC AWARENESS:
If this encounter could be a moment where a front's twist is revealed — a turning point where the story's hidden question becomes visible through consequences — encode that potential in the secret layer. The encounter doesn't force the reveal; it creates the conditions where it COULD happen if the PCs push in the right direction. Check the front's `ai:secret` layers and consider whether this scene is where the dissonance between surface and depth becomes tangible.
