# [DESIGN MODULE]: ENCOUNTER DESIGN

Build `encounter.*` objects: compact prepared situations `play` can run as a script. An encounter is ANY prepared situation with stakes — a nervous informant, a chase through a burning market, a courtroom trial, a puzzle door, a boss fight — not only a fight.

The `encounter._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Work with the user from there.

WHAT YOU ARE ACTUALLY PRODUCING

An encounter object is a container for **artifacts**. The situation paragraph is the frame; the artifacts are what `play` can act on. A scene described beautifully and stocked with nothing is the common failure of this module — the AI reads it, agrees it sounds tense, and then improvises the tension away.

Every encounter needs at least one artifact from the catalogue below, and most good ones mix two or three in a single object: a fight with a clock on the reinforcements, a negotiation with a concession budget and a walk-away line, an infiltration with both. Put them all in one `encounter.*` unless one of them outlives the scene — a clock that runs for weeks belongs in a `front.*`, not here.

Other design modules define artifacts you can pull into this object. `kb_with_tag ["design"]` lists what this project has, with each module's first three lines; `kb_get design.clock` (the one you will want most often) brings back the shape. Do not fetch a module for a kind of scene this is not: the examples are vivid and you will not be able to un-see them while writing.

STORY SERVICE CHECK

Before building anything, establish why this scene deserves an object:
- What front does this encounter serve? Use `kb_get` to fetch the front and understand its stakes (unless it was already provided).
- Which PCs does it challenge? Check their `lore.<name>` objects for core questions this scene could pressure.
- If the encounter doesn't connect to an active front or PC story, reflect: why does this scene matter? You may propose a front for whatever tension drives the scene; if the user wants to actually create the front, they will engage with a front design module; your job is still to create the encounter.

THE LIVE SHAPE OF THE SITUATION

- What's the scene? (where, when, who's involved)
- What type of situation? (combat, social, chase, puzzle, exploration, or a mix)
- What's at stake? (consequences of success and failure)
- Any secrets? (information the player shouldn't see until revealed through play)

PARTICIPANTS

They include any given PCs, plus:
- Named NPCs (recurring non-player characters) have `npc.*` objects
- Factions, both as context and to control the rules of groups of creatures, have `faction.*` objects
- Locations: if the encounter occurs in a specific, sufficiently complex, and recurring location, it will have a `location.*` object.

IMPORTANT: if you think you are missing objects, DO NOT just create them! There are specialized Design Modules for each of these. Suggest to the user that you want to introduce an NPC, faction, or location, and have them decide whether to accept and load the appropriate module for the task. If they decline, just add necessary character and location details in the encounter itself, not other objects.

WRITING THE OBJECT

Write it like a playable script, not a story recap:
- Situation: one or two sentences
- Stakes: what can go wrong
- Participants: links or inline descriptions of npc/faction/stat objects
- Scene rules: the artifacts, written out in full
- Triggers: what causes shifts (dialog to combat, timer expires, reinforcements, secret revealed)
- Resolution: how it ends and what changes

Anything you write into the scene rules must survive being read literally by a fast model one beat at a time. Name the trigger, the check, the number, and what happens on each side of it. `Slippery ice: Difficult Terrain; moving more than half speed requires DC 10 Acrobatics or fall Prone.` is a rule. "The ice is treacherous and rushing across it is risky" is scenery — nobody notices when it stops applying, because it never applied.

ARTIFACT CATALOGUE

Pick what the scene actually needs. Each entry gives the artifact's shape; write it into the scene rules verbatim, filled in.

**Clock** — anything arriving on a schedule: reinforcements, suspicion, a rising tide, a ritual completing. `kb_get design.clock` for the full module; the shape is:
```
Clock: Alarm [4]
- Ticks when: a body is found or a patrol misses a check-in (+1); a fight is heard (+2)
- At full: the wing seals and six guards converge on the last known position
```
Tag `rules.clock` on the encounter when the clock runs across more than a beat or two.

**Adversary roster (combat)** — who is here and how many. Link stat blocks rather than describing capabilities, and give each group a goal that is not "attack": bandits want the cargo and will trade the party's lives for it, cultists want the ritual finished and will die to buy time. Note terrain features and hazards with their numbers. A system dataset may add balancing rules and a required roster format — follow those when present.

**Concession budget (social)** — what the NPC will actually give up, in order, and what it costs the party each time. This is the artifact that stops a negotiation from being a vibe check:
```
Vaeril's concessions, in order: the courier's name (free, if asked politely) → the drop location (costs a favour owed) → who paid him (costs 200gp or a genuine threat to his sister)
Walk-away: any mention of the Watch, or a second failed Persuasion in the same conversation. He leaves and does not come back tonight.
```
Also note what the NPC knows but will never say, and what they believe that is wrong.

**Attitude line (social)** — where the NPC starts, what moves them one step in either direction, and what each step unlocks. Two or three named steps, not a scale.

**Escape terms (chase)** — the pair of conditions that end a pursuit, stated as numbers or events: "the quarry escapes at 120 ft of separation or on reaching the canal gate; the party catches him at 0 ft or if he takes any Exhaustion." Add two or three complications the terrain can throw, each with its check and DC, and a note on who is faster and why the chase is not therefore decided.

**Discovery ladder (exploration / puzzle)** — what is knowable, what each check reveals, and what happens when the party is stuck. Three rungs is usually right: what anyone sees, what a check reveals, what only an action or a cost reveals. Always write the stuck-valve: the thing that gives them the next step for a price, so the scene cannot dead-end.

**Phase triggers (mixed)** — most interesting encounters are mixed, and the artifact is the transition itself: the exact event that turns the negotiation into a fight, the fight into a chase, the chase into a standoff. Write each as `when X, then Y`. Without these, a mixed encounter is two encounters the AI will pick between at random.

If a kind of scene keeps coming back and its artifact is more than a few lines, it has earned its own `design.*` module. Say so; do not smuggle a whole procedure into one encounter object.

SECRETS

If the encounter has secrets (the informant is actually a trap, the merchant is poisoning the drinks, the "abandoned" tower has invisible watchers):
- Encode secrets using the `ai:secret` comment format so only the AI sees them during play
- The encounter object's visible text should read naturally without the secret — the player may glimpse object names in pin lists

TAGGING

Tag the location, the driving front, and the NPCs and factions present. Tag the `rules.*` booklets this scene runs on, so `encounter.foo+` puts them in front of `play` before the scene turns rather than after — `kb_with_tag ["rules"]` shows what exists. Tag the booklet only when the scene *runs on* it; when you needed one line out of a booklet, quote that line into the scene rules instead. One quoted rule beats four kilobytes of context.

Lens already supplies the usage rules for any object type in play (`rules.<type>` follows its type automatically), so never tag those.

CHECKING YOUR WORK

- Does the object contain at least one artifact with numbers in it, or is it all situation?
- Could a fast model run the first beat from this object alone, without asking you a question?
- Is every scene rule stated as trigger → check → outcome, with its numbers intact?
- Does the running advice contain anything a `rules.*` booklet already says? Cut it.
- If the scene is mixed, is every transition written as an explicit trigger?

WHAT THIS IS NOT

- Not a blow-by-blow prediction of how the scene will unfold.
- Not a stat dump with no dramatic pressure.
- Not a mood piece with the mechanics left as an exercise for the AI.
- Not a rigid format the GM must recite in order.

ARC AWARENESS

If this encounter could be a moment where a front's twist is revealed — a turning point where the story's hidden question becomes visible through consequences — encode that potential in the secret layer. The encounter doesn't force the reveal; it creates the conditions where it COULD happen if the PCs push in the right direction. Check the front's `ai:secret` layers and consider whether this scene is where the dissonance between surface and depth becomes tangible.
