# [DESIGN MODULE]: ENCOUNTER DESIGN

Build `encounter.*` objects — prepared situations for play to use as scripts. An encounter is ANY prepared situation with stakes, not only a fight.

The **`encounter._template`** layout is included in RELEVANT KNOWLEDGE when you use this module. **Follow its three sections in order** (`## Situation`, `## Running non-PC characters`, `## Prep and reference`). Do not collapse them into one flat bullet list.

STEP 0: STORY SERVICE CHECK
Before building anything, establish the connection to the story:
- What front does this encounter serve? Use `kb_get` to fetch the front and understand its stakes (unless it was already provided).
- Which PCs does it challenge? Check their `lore.<name>` objects for core questions this scene could pressure.
- If the encounter doesn't connect to an active front or PC story, reflect: why does this scene matter? You may propose a front; your job is still to create the encounter.

1: UNDERSTAND THE SITUATION
Ask about:
- What's the scene? (where, when, who's involved)
- What type of situation? (combat, social, chase, puzzle, exploration, or a mix)
- What's at stake? (consequences of success and failure)
- Any secrets? (information the player shouldn't see until revealed through play)

2: ASSEMBLE PARTICIPANTS
Participants include any given PCs, plus:
- Named NPCs (recurring non-player characters) have `npc.*` objects
- Factions have `faction.*` objects
- Locations: if the encounter is in a specific, sufficiently complex, recurring place, it may have a `location.*` object

IMPORTANT: if you think you are missing objects, DO NOT just create them! There are specialized Design Modules for each of these. Suggest that the user load the appropriate module; if they decline, add necessary detail in the encounter itself, not new objects.

3: COMBAT BALANCING (when the scene includes the possibility of combat)
- `kb_get` **`rules.system`** if you need how combat is framed for this table.
- Take PC levels from pinned **`pc.*`** objects (e.g. tags **`level:N`**).
- Discover enemies: `stat._template` describes conventions; use **`kb_with_tag`** to find **`stat.*`** candidates (CR, type, habitat, etc.). Rank by **narrative fit** first.
- Use **`balance_encounter`** on your ranked list. Pass **`pcs`** as one level per PC. Pass **`allies`** in the **same shape as `required`**: `{ "id": "stat.…", "count": N }` per allied stat block that fights on the party's side. The tool reads each ally's **`cr:`** tags and adds **count × build XP** to the budget so enemy totals match **PCs plus exactly those allies** — use the same ids and counts you will list under Prep.
- If you change the ally roster after balancing, call the tool again with updated **`allies`**.
- When the tool returns creature IDs and counts, you **must** note every fighting **`stat.*`** into **`## Prep and reference`** as **`N× KB['stat.…']`** lines (same token shape as pinned objects in context). Do **not** paste full stat text into the encounter. Do **not** use **`KB['…']`** for other object types (PCs etc.) as pins already surface those. Do **not** scatter **`KB['stat.…']`** outside **`## Prep and reference`**.
- Also tag the encounter object with every **`stat.*`** that appears in **`## Prep and reference`**. This is important: the Prep roster is for the human-readable script, but the tags are what let `encounter.some-scene+` pull those stat blocks into play context later.

4: WRITE THE ENCOUNTER OBJECT
**Part 1 — `## Situation`:** Situation, stakes, initial positions, scene rules, triggers, resolution. Name participants in prose or with dot-ids (`pc.*`, `faction.*`). No **`KB['…']`** tokens here. If combat is not a given, state how narratively it would be triggered or avoided. For combat/physical encounters, include **initial positions**: starting distances between groups in feet, formations, terrain zones, cover, elevation, and chokepoints — enough for theater-of-mind spatial tracking.

**Part 2 — `## Running non-PC characters`:** Defaults are in the template (player runs the table; AI answers when asked, grounded in stats/objects). Add only encounter-specific tactics, priorities, morale, triggers.

**Part 3 — `## Prep and reference`:** For combat, **mandatory** **`KB['stat.…']`** roster with counts (foes and allied **`stat.*`** that need blocks). Non-combat or no stat-backed creatures: note **`— none`** or omit stat lines.

**Tags on the encounter object:** Include story links as usual (`location.*`, relevant `front.*`, `npc.*`, `faction.*`). In addition, tag every referenced **`stat.*`** so `encounter.*+` expands to the combatants. Note: `rules.encounter` auto-pins when any `encounter.*` is in play context — no need to tag it. Tag other `rules.*` only if the scene depends on specialized procedures beyond standard encounter running (e.g. a future `rules.chase`).

Common mistakes: calling **`balance_encounter`** but skipping the Prep stat list; pasting stat bodies instead of tokens; **`KB['stat.…']`** outside Prep; **`allies`** in the tool that don't match the allied **`stat.*`** lines you write in Prep (ids or counts). You should never emit kb items for any other object type (faction, npc, location, etc.), only the encounter.

5: SECRETS
Encode secrets with **`ai:secret`**. Visible text should read naturally without the secret.

APPENDIX - ENCOUNTER TYPES
These are guidelines for scene rules, not separate templates or rigid categories:

**Combat**: Link stat blocks or create mechanically interesting adversaries. Note terrain features, environmental hazards, and enemy goals. Enemies have motivations — bandits flee when losing, cultists sacrifice themselves, intelligent foes adapt.

**Social**: Note each NPC's goals, what they know, what they'll share freely, and what requires checks. Conversation encounters don't need rolls for every exchange — only when the PC pushes past what the NPC would naturally give.

**Chase/Escape**: Note starting distance, terrain type, potential complications, exhaustion rules. What ends the chase (distance, hiding, obstacle, confrontation)?

**Puzzle/Exploration**: Note the puzzle mechanics, what information is available, what checks reveal. What happens if they get stuck? What happens if they brute-force it?

**Mixed**: Most interesting encounters are mixed. Note the triggers that shift between types. A negotiation that could become a fight. A combat that the quarry flees from. A puzzle room with a guardian. Write the triggers explicitly.

ARC AWARENESS:
If this encounter could be a moment where a front's twist is revealed — a turning point where the story's hidden question becomes visible through consequences — encode that potential in the secret layer. The encounter doesn't force the reveal; it creates the conditions where it COULD happen if the PCs push in the right direction. Check the front's `ai:secret` layers and consider whether this scene is where the dissonance between surface and depth becomes tangible.
