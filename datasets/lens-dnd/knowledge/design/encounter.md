# [DESIGN MODULE]: ENCOUNTER DESIGN

Build `encounter.*` objects — prepared situations for play to use as scripts, with the artifacts a fast model can actually run from. An encounter is ANY prepared situation with stakes, not only a fight.

The **`encounter._template`** layout is included in RELEVANT KNOWLEDGE when you use this module. **Follow its three sections in order** (`## Situation`, `## Running non-PC characters`, `## Prep and reference`). Do not collapse them into one flat bullet list.

THE RULES SHELF
Two rules objects are linked to this module and are already in RELEVANT KNOWLEDGE, because every encounter needs both: **`rules.system`** (the base this table runs on) and **`rules.encounter`** (how `play` will actually run the object you are writing — write for that procedure).

The rest of the shelf depends on what kind of scene this is, so it is not loaded and it is not listed here. Find it: **`kb_with_tag ["rules"]`** returns every play-time booklet this project has, each with its first three lines saying what it covers and when it applies. `kb_get` only the ones this scene actually calls for — a quiet negotiation in a parlour needs none of them, and a booklet full of chase examples fetched "just in case" is a page of the wrong scene you will not be able to un-see while writing this one.

If the user already knows what kind of scene this is, they can save you even the lookup by mentioning or including the ruleset in their opening request (`--include rules.combat`, or `@rules.chase` in the prompt).

You can reach all of this and `play` cannot. During play the model gets `rules.system` plus whatever the scene turns into; everything else arrives at the table only because **you** put it there. That is the point of prep.

ARTIFACTS, AND MIXING MODULES
The situation paragraph is the frame; the **artifacts** are what `play` can act on. An encounter with a beautiful scene and no artifact gets improvised away in one beat.

Other design modules define artifacts you can compose into this one object — **`kb_with_tag ["design"]`** lists them with their first three lines. The one you will reach for most is **`design.clock`**, for anything arriving on a schedule (reinforcements, suspicion, a rising tide, a ritual completing); fetch it with `kb_get` and write the clock into the scene rules. Several artifacts in one `encounter.*` is the normal case — a fight with a clock on the reinforcements, a negotiation with a concession budget and a walk-away line. Split into separate objects only when one artifact outlives the scene: a clock that runs for weeks belongs on a `front.*`.

A tracker is the exception that is its own object: once initiative is rolled, `design --module tracker` builds a live `tracker.*` from this encounter's roster. Do not attempt one from here.

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
- `kb_get` **`rules.combat`** if you need how a fight is framed at this table (unless it is already in context).
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

**Tags on the encounter object:** Include story links as usual (`location.*`, relevant `front.*`, `npc.*`, `faction.*`). In addition, tag every referenced **`stat.*`** so `encounter.*+` expands to the combatants. Note: `rules.encounter` auto-pins when any `encounter.*` is in play context — no need to tag it.

**Tag the rules this scene needs.** `play` starts with only the base rules; a tag on the encounter is what puts a booklet in front of it *before* the scene turns, with no round trip and no chance the model fails to notice. Work from the list `kb_with_tag ["rules"]` gives you, and tag by trigger, not by theme: violence is *possible* here (including the negotiation that could go wrong and the heist that could be discovered), someone is likely to run, the world itself is part of the problem, a clock has to be run across beats.

**Tag the booklet, or quote the rule — whichever is smaller.** A tag hands `play` the whole object on every beat of the scene. That is right when the scene *runs on* those rules: a fight needs all of the combat booklet, a pursuit needs all of the chase one. It is wrong when you opened a booklet and took one or two lines out of it. If the encounter needs nothing from the environment rules but the ice rule, quote the ice rule into the scene rules and do not tag it — one line beats four kilobytes, and quoting is what §5 asks for anyway.

Do **not** tag rules objects onto each other, and do not tag `rules.system` — it is always present in play. Lens supplies `rules.<type>` companions automatically for every type in the scene (`rules.encounter`, `rules.stat`, `rules.tracker`), so never tag those either; the deduplication that gives you is the point.

Common mistakes: calling **`balance_encounter`** but skipping the Prep stat list; pasting stat bodies instead of tokens; **`KB['stat.…']`** outside Prep; **`allies`** in the tool that don't match the allied **`stat.*`** lines you write in Prep (ids or counts). You should never emit kb items for any other object type (faction, npc, location, etc.), only the encounter.

5: SCENE RULES — QUOTE THEM, OR WRITE THEM
A scene often needs a procedure that no module covers: the auction, the collapsing stair, the rite that has to be interrupted in a specific order. You are the only part of this system that can prepare one, because `play` sees a beat at a time and answers fast.

**Quoting.** When a rule you already have applies, copy it into the scene rules **verbatim, with its numbers**. Never soften a rule into a description. `Slippery Ice: Difficult Terrain. Walking requires DC 10 Acrobatics or fall Prone.` is a rule; "ice is difficult terrain and crossing it briskly risks going down" is not a rule at all — it reads like guidance, so nobody notices it is gone, and the AI cannot act on it. If a rule is not worth its numbers, leave it out rather than paraphrasing it.

**Inventing.** When nothing fits, write the procedure yourself. This is allowed and encouraged: a fast model with a little structure in front of it behaves far better than one improvising, which either yes-ands everything or invents something unhinged and then commits to it for the rest of the scene. An invented rule must look like a rule:
- Name the trigger, the check (ability or skill), the DC, and what happens on success and on failure.
- Give it a cost or a clock, so it can end.
- Keep it consistent with the base rules — you may add a procedure, not overturn how a D20 test works.

Good: `Rising water: at the end of each round the water rises one foot. At 3 feet the floor is Difficult Terrain; at 5 feet Small creatures must swim (DC 12 Athletics each round or lose their action).`
Bad: "the water keeps rising and it gets harder to move."

6: SECRETS
Encode secrets with **`ai:secret`**. Visible text should read naturally without the secret.

APPENDIX - ARTIFACTS BY SCENE TYPE
Not categories and not templates: these are the artifacts each kind of scene needs in `## Situation` under Scene rules. Write them out filled in, with their numbers. Mix freely — most good encounters carry two or three.

**Combat — adversary roster.** The `KB['stat.…']` lines in Prep, plus, for each group, a goal that is not "attack": bandits want the cargo and will trade your lives for it, cultists want the ritual finished and will die to buy time. Note the terrain features and hazards that matter with their DCs, and the point at which each group breaks — a flee threshold in HP, in losses, or in a named event.

**Social — concession budget and walk-away.** What the NPC will actually give up, in order, and what each step costs the party:
```
Vaeril concedes, in order: the courier's name (free, if asked civilly) → the drop location (a favour owed) → who paid him (200gp, or a credible threat to his sister)
Walk-away: any mention of the Watch, or a second failed Persuasion in one conversation. He leaves; he is not available again tonight.
```
Add his starting attitude and what moves it a step each way, what he knows but will never say, and what he believes that is wrong. Conversation encounters don't need rolls for every exchange — only when the PC pushes past what the NPC would naturally give, and the budget is what tells you where that line is.

**Chase/Escape — escape terms.** The pair of conditions that end it, as numbers or events: "escapes at 120 ft of separation or on reaching the canal gate; caught at 0 ft, or if he takes any level of Exhaustion." Plus two or three terrain complications, each with its check and DC, and a note on who is faster and why that does not already decide it.

**Puzzle/Exploration — discovery ladder.** Three rungs: what anyone sees, what a check reveals (name it and give the DC), what only an action or a cost reveals. Always write the stuck-valve — the thing that hands them the next step for a price — so the scene cannot dead-end.

**Any scene under time pressure — a clock.** `kb_get design.clock`. Reinforcements, suspicion, a rising tide, a ritual reaching its verse.

**Mixed — phase triggers.** Most interesting encounters are mixed, and the artifact is the transition itself. Write each as `when X, then Y`: the exact event that turns the negotiation into a fight, the fight into a chase, the chase into a standoff. Without these, a mixed encounter is two encounters the AI picks between at random.

ARC AWARENESS:
If this encounter could be a moment where a front's twist is revealed — a turning point where the story's hidden question becomes visible through consequences — encode that potential in the secret layer. The encounter doesn't force the reveal; it creates the conditions where it COULD happen if the PCs push in the right direction. Check the front's `ai:secret` layers and consider whether this scene is where the dissonance between surface and depth becomes tangible.
