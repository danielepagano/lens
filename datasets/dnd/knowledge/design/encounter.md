# [DESIGN MODULE]: ENCOUNTER DESIGN

Build `encounter.*` objects — prepared situations for `play` to use as scripts. An encounter is ANY prepared situation with stakes, not just combat. A conversation with a nervous informant, a chase through a burning market, a courtroom trial, a puzzle door, a boss fight — these are all encounters.

Fetch `encounter._template` first. Then work with the user.

STEP 0: STORY SERVICE CHECK
Before building anything, establish the connection to the story:
- What front does this encounter serve? Use `kb_get` to fetch the front and understand its stakes.
- Which PCs does it challenge? Check their `lore.<name>` objects for core questions this scene could pressure.
- If the encounter doesn't connect to an active front or PC story, push back: why does this scene matter? If the user wants it anyway, suggest creating a front stub for whatever tension drives the scene.

STEP 1: UNDERSTAND THE SITUATION
Ask about:
- What's the scene? (where, when, who's involved)
- What type of situation? (combat, social, chase, puzzle, exploration, or a mix)
- What's at stake? (consequences of success and failure)
- Any secrets? (information the player shouldn't see until revealed through play)

STEP 2: BUILD PARTICIPANTS
For each participant, check if a KB object already exists (`kb_get`). If not:
- Named NPCs who recur: create `npc.*` objects (fetch `npc._template`)
- Factions acting as groups: create or link `faction.*` objects
- Monsters/enemies for combat: link to `stat.*` objects by tag search

STEP 3: COMBAT BALANCING (if applicable)
If the encounter includes combat:
- Identify PC levels from pinned `pc.*` objects (check `level:N` tags)
- Use `kb_with_tag` to find stat block candidates by CR, habitat, and type
- Rank candidates by narrative fit (a goblin ambush wants goblins, not random CR-appropriate monsters)
- Call `balance_encounter` with required monsters, ranked optionals, difficulty, PC levels, and any ally CRs
- Pick from the proposals and include the selected stat block links in the encounter object

STEP 4: WRITE THE ENCOUNTER OBJECT
The encounter object should be compact — aim for under 300 words in the body. It's a script, not a novel:
- Situation: one or two sentences
- Stakes: what can go wrong
- Participants: links to npc/faction/stat objects
- Scene rules: special mechanics. KEEP SHORT. If complex (multi-room dungeon, heist phases), write a brief summary here and link to a `lore.*` object with full details
- Triggers: what causes shifts (dialog to combat, timer expires, reinforcements, secret revealed)
- Resolution: how it ends and what changes

STEP 5: SECRETS
If the encounter has secrets (the informant is actually a trap, the merchant is poisoning the drinks, the "abandoned" tower has invisible watchers):
- Encode secrets using the `ai:secret` comment format so only the AI sees them during play
- The encounter object's visible text should read naturally without the secret — the player may glimpse object names in pin lists

ENCOUNTER TYPES — NOT RIGID CATEGORIES:
These are guidelines for scene rules, not separate templates:

**Combat**: Link stat blocks. Note terrain features, environmental hazards, and enemy goals (not just "attack"). Enemies have motivations — bandits flee when losing, cultists sacrifice themselves, intelligent foes adapt.

**Social**: Note each NPC's goals, what they know, what they'll share freely, and what requires checks. Conversation encounters don't need rolls for every exchange — only when the PC pushes past what the NPC would naturally give.

**Chase/Escape**: Note starting distance, terrain type, potential complications, exhaustion rules. What ends the chase (distance, hiding, obstacle, confrontation)?

**Puzzle/Exploration**: Note the puzzle mechanics, what information is available, what checks reveal. What happens if they get stuck? What happens if they brute-force it?

**Mixed**: Most interesting encounters are mixed. Note the triggers that shift between types. A negotiation that could become a fight. A combat that the quarry flees from. A puzzle room with a guardian. Write the triggers explicitly.

ARC AWARENESS:
If this encounter could be a moment where a front's twist is revealed — a turning point where the story's hidden question becomes visible through consequences — encode that potential in the secret layer. The encounter doesn't force the reveal; it creates the conditions where it COULD happen if the PCs push in the right direction. Check the front's `ai:secret` layers and consider whether this scene is where the dissonance between surface and depth becomes tangible.
