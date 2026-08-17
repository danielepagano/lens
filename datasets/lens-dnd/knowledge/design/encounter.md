# [DESIGN MODULE]: ENCOUNTER DESIGN

Build `encounter.*` objects — prepared situations for play to use as scripts. An encounter is ANY prepared situation with stakes, not only a fight.

The **`encounter._template`** layout is included in RELEVANT KNOWLEDGE when you use this module. **Follow its three sections in order** (`## Situation`, `## Running non-PC characters`, `## Prep and reference`). Do not collapse them into one flat bullet list.

An encounter is the usual place to put several prepared things at once — the antagonists, the clock, the way out of the conversation. They go in this object by default, because this is the object the scene pins. Anything split out gets tagged here so `encounter.<key>+` still carries it.

THE RULES SHELF
Two rules objects are linked to this module and are already in RELEVANT KNOWLEDGE, because every encounter needs both: **`rules.system`** (the base — DCs, attitudes and Influence, vision and hiding, conditions, dying, resting) and **`rules.encounter`** (how `play` will actually run the object you are writing — write for that procedure).

The rest of the shelf depends on what kind of scene this is, so it is not loaded — and it is not listed here either, because a list in one module goes stale the moment the dataset gains a booklet. Find it: **`kb_with_tag ["rules"]`** returns every booklet with its opening lines, which state what it covers and when it applies. Then `kb_get` only the ones this scene actually calls for.

A quiet negotiation in a parlour needs none of them, and loading one you do not need is worse than the tool call it saved: a shelf of combat procedure will colour every line you write afterwards. If the user already knows what kind of scene this is, they can save you even the lookup by mentioning or including the ruleset in their opening request (`--include rules.combat`, or `@rules.chase` in the prompt).

You can reach all of this and `play` cannot. During play the model gets `rules.system` plus whatever the scene turns into; everything else arrives at the table only because **you** put it there. That is the point of prep.

STEP 0: STORY SERVICE CHECK
The fiction is given; the mechanism is yours. Why this confrontation matters and what it is secretly about comes from the front, its prep, or the user — the positions, the numbers, the triggers, and the way out are what you invent. If the scene cannot be built without settling a story question nobody answered, say so and stop.

Before building anything, establish the connection to the story:
- What front does this encounter serve? Use `kb_get` to fetch the front and understand its stakes (unless it was already provided).
- Which PCs does it challenge? Check their `lore.<name>` objects for core questions this scene could pressure.
- If the encounter doesn't connect to an active front or PC story, reflect: why does this scene matter? You may propose a front; your job is still to create the encounter.

1: UNDERSTAND THE SITUATION
Ask about:
- What's the scene? (where, when, who's involved)
- What type of situation? (combat, social, chase, puzzle, exploration, or a mix)
- What's at stake? (consequences of success and failure)
- What is not what it appears to be? (anything the player should discover through play rather than read off a pin list)

2: ASSEMBLE PARTICIPANTS
Participants include any given PCs, plus:
- Named NPCs (recurring non-player characters) have `npc.*` objects
- Factions have `faction.*` objects
- Locations: if the encounter is in a specific, sufficiently complex, recurring place, it may have a `location.*` object

Missing an NPC, faction, or location object? Do not create it here — say what you want to introduce and let the user load that module.

3: COMBAT BALANCING (when the scene includes the possibility of combat)
- `kb_get` **`rules.combat`** if you need how a fight is framed at this table (unless it is already in context).
- Take PC levels from pinned **`pc.*`** objects (e.g. tags **`level:N`**).
- Discover enemies: `stat._template` describes conventions; use **`kb_with_tag`** to find **`stat.*`** candidates (CR, type, habitat, etc.). Rank by **narrative fit** first.
- Use **`balance_encounter`** on your ranked list. Pass **`pcs`** as one level per PC. Pass **`allies`** in the **same shape as `required`**: `{ "id": "stat.…", "count": N }` per allied stat block that fights on the party's side. The tool reads each ally's **`cr:`** tags and adds **count × build XP** to the budget so enemy totals match **PCs plus exactly those allies** — use the same ids and counts you will list under Prep.
- If you change the ally roster after balancing, call the tool again with updated **`allies`**.
- When the tool returns creature IDs and counts, you **must** note every fighting **`stat.*`** into **`## Prep and reference`** as **`N× KB['stat.…']`** lines (same token shape as pinned objects in context). Do **not** paste full stat text into the encounter. Do **not** use **`KB['…']`** for other object types (PCs etc.) as pins already surface those. Do **not** scatter **`KB['stat.…']`** outside **`## Prep and reference`**.
- Also tag the encounter object with every **`stat.*`** that appears in **`## Prep and reference`**. This is not bookkeeping: the Prep roster is the human-readable script, and the **tags** are the only thing that puts those stat blocks in front of `play`, via `encounter.some-scene+`. `play` has no `kb_get` — it cannot fetch a block you forgot to tag. A roster line reading `4× KB['stat.bandit']` with no matching tag produces a GM that has been told to act from a stat block it cannot see, and it will improvise the creature instead.

4: WRITE THE ENCOUNTER OBJECT
**Part 1 — `## Situation`:** Situation, stakes, initial positions, scene rules, triggers, resolution. Name participants in prose or with dot-ids (`pc.*`, `faction.*`). No **`KB['…']`** tokens here. If combat is not a given, state how narratively it would be triggered or avoided. For combat/physical encounters, include **initial positions**: starting distances between groups in feet, formations, terrain zones, cover, elevation, and chokepoints — enough for theater-of-mind spatial tracking.

**Part 2 — `## Running non-PC characters`:** Defaults are in the template (player runs the table; AI answers when asked, grounded in stats/objects). Add only encounter-specific tactics, priorities, morale, triggers.

**Part 3 — `## Prep and reference`:** Combat encounters only, and then **mandatory**: a **`KB['stat.…']`** roster with counts (foes and allied **`stat.*`** that need blocks). A scene with no stat-backed creatures omits the section entirely — the template licenses it for combat and nothing else.

**Tags on the encounter object:** Include story links as usual (`location.*`, relevant `front.*`, `npc.*`, `faction.*`). In addition, tag every referenced **`stat.*`** so `encounter.*+` expands to the combatants. Note: `rules.encounter` auto-pins when any `encounter.*` is in play context — no need to tag it.

**Tag the rules this scene needs.** `play` starts with only the base rules; a tag on the encounter is what puts a module in front of it *before* the scene turns, with no round trip and no chance the model fails to notice:
- Tag **`rules.combat`** on any encounter where violence is possible — not only on set-piece fights, but on the negotiation that could go wrong and the heist that could be discovered.
- Tag **`rules.chase`** when someone is likely to run: a quarry, a courier, a creature that flees when bloodied.
- Tag **`rules.environment`** when the world is part of the problem — weather, hazards, deep water, a long journey.

**Tag the module, or quote the rule — whichever is smaller.** A tag hands `play` the whole object on every beat of the scene. That is right when the scene *runs on* those rules: a fight needs all of `rules.combat`, a pursuit needs all of `rules.chase`. It is wrong when you opened a ruleset and took one or two lines out of it. If the encounter needs nothing from `rules.environment` but the ice rule, quote the ice rule into the scene rules and do not tag it — one line beats four kilobytes, and quoting is what §5 asks for anyway.

Do **not** tag rules objects onto each other, and do not tag `rules.system` — it is always present in play.

Common mistakes: calling **`balance_encounter`** but skipping the Prep stat list; pasting stat bodies instead of tokens; **`KB['stat.…']`** outside Prep; **`allies`** in the tool that don't match the allied **`stat.*`** lines you write in Prep (ids or counts). You should never emit kb items for any other object type (faction, npc, location, etc.), only the encounter.

5: SCENE RULES — QUOTE THEM, OR WRITE THEM
A scene often needs a procedure that no module covers: the auction, the collapsing stair, the rite that has to be interrupted in a specific order. You are the only part of this system that can prepare one, because `play` sees a beat at a time and answers fast.

**Deltas only.** `rules.encounter` is in front of `play` on every beat and already says how a prepared scene is run; `rules.combat` says how a fight is run. This section holds what is DIFFERENT about this scene — values, triggers, exceptions — and never a second telling of a procedure. A re-explained rule drifts from the booklet, and at play time nothing tells the model which copy wins.

**Quoting.** When a rule you already have applies, copy it into the scene rules **verbatim, with its numbers**. Never soften a rule into a description. `Slippery Ice: Difficult Terrain. Walking requires DC 10 Acrobatics or fall Prone.` is a rule; "ice is difficult terrain and crossing it briskly risks going down" is not a rule at all — it reads like guidance, so nobody notices it is gone, and the AI cannot act on it. If a rule is not worth its numbers, leave it out rather than paraphrasing it.

**Inventing.** When nothing fits, write the procedure yourself. This is allowed and encouraged: a fast model with a little structure in front of it behaves far better than one improvising, which either yes-ands everything or invents something unhinged and then commits to it for the rest of the scene. An invented rule must look like a rule:
- Name the trigger, the check (ability or skill), the DC, and what happens on success and on failure.
- Give it a cost or a clock, so it can end.
- Keep it consistent with the base rules — you may add a procedure, not overturn how a D20 test works.

Good: `Rising water: at the end of each round the water rises one foot. At 3 feet the floor is Difficult Terrain; at 5 feet Small creatures must swim (DC 12 Athletics each round or lose their action).`
Bad: "the water keeps rising and it gets harder to move."

6: WHAT THE PLAYER MUST NOT READ YET
A prepared scene almost always knows something the player does not. Whatever `play` has to act on the moment the scene starts stays in the encounter object — it is not prep, it is the scene — kept out of the object's plain visible text, which must still read correctly if the fact never comes out.

The encounter's **back** — `encounter.<key>-prep`, expanded into design and advance sessions and never into `play`'s — is for the other thing: what this scene is a step toward, which follow-up it sets up, why the front placed it here. Most encounters need none, and a scene-time fact put there would never reach the table.

ARC AWARENESS:
If this encounter is where a front's twist could surface — a turning point where the story's buried question becomes visible through consequences — prepare the conditions for it, not the reveal. Read the front and its prep for what the arc is actually about, and build the scene so the dissonance between surface and depth becomes tangible if the PCs push in that direction. The encounter never forces it.
