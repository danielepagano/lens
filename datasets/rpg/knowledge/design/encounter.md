# [DESIGN MODULE]: ENCOUNTER DESIGN

Build `encounter.*` objects: compact situations the GM can actually run. An encounter is ANY prepared situation with stakes — an informant meeting, a chase through a burning market, a courtroom trial, a puzzle door, a boss fight — and the object is the script `play` follows.

The `encounter._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Work with the user from there.

An encounter is the most common home for several artifacts at once. Write the antagonists, the clock, the social ladder out, and the terrain rule INTO this one object — it is the object the scene will pin, and `play` sees one thing and has the whole situation. Split an artifact into its own object only when it outlives this scene or is reused by another; then tag it here so `encounter.<key>+` still carries it.

Before building anything, establish why this scene deserves an object:
- What front does this encounter serve? Use `kb_get` to fetch the front and understand its stakes (unless it was already provided).
- Which PCs does it challenge? Check their `lore.<name>` objects for core questions this scene could pressure.
- If the encounter doesn't connect to an active front or PC story, reflect: why does this scene matter? You may propose a front for whatever tension drives the scene; if the user wants to actually create the front, they will engage with a front design module; your job is still to create the encounter.

Get the live shape of the situation:
- What's the scene? (where, when, who's involved)
- What type of situation? (combat, social, chase, puzzle, exploration, or a mix)
- What's at stake? (consequences of success and failure)
- Any secrets? (information the player shouldn't see until revealed through play)

Assemble the participants cleanly. They include any given PCs, plus:
- Named NPCs (recurring non-player characters) have `npc.*` objects
- Factions, both as context and to control the rules of groups of creatures, have `faction.*` objects
- Locations: if the encounter occurs in a specific, sufficiently complex, and recurring location, it will have a `location.*` object.

Missing an NPC, faction, or location object? Do not create it here — say what you want to introduce and let the user load that module.

Write the encounter object like a playable script, not a story recap:
- Situation: one or two sentences
- Stakes: what can go wrong
- Participants: links or inline descriptions of npc/faction/stat objects
- Scene rules: the artifacts. See the appendix for what each kind of situation owes you.
- Triggers: what causes shifts (dialog to combat, timer expires, reinforcements, secret revealed)
- Resolution: how it ends and what changes

SCENE RULES: DELTAS, AND KEEP THE NUMBERS

`rules.encounter` already tells `play` how to run a prepared scene, and it is in front of the model on every beat. This object states only what is DIFFERENT here — the values, the triggers, the exceptions. Never re-explain a procedure. "Alarm clock 4; full means reinforcements, not detection; guards rotate every 10 minutes" is right. A paragraph on how clocks work is a second copy of a rule that will drift from the booklet, and at play time nobody can tell which copy wins.

Two ways to get a scene rule, both fine:
- **Quote** an existing rule verbatim, with its numbers, when one applies. Never soften it into description — "Slick planks: Difficult Terrain; crossing at a run is DC 10 Acrobatics or fall Prone" is a rule; "the planks are treacherous when wet" is not, and nobody will notice the rule went missing.
- **Invent** one when nothing fits. This is encouraged: a fast model with a little structure behaves far better than one improvising a subsystem mid-beat. An invented rule must look like a rule — name the trigger, the check, the difficulty, and what happens on success and failure — and it must have a cost or a clock so it can end. Add procedure; never overturn how the system's basic resolution works.

SECRETS
If the encounter has secrets (the informant is actually a trap, the merchant is poisoning the drinks, the "abandoned" tower has invisible watchers):
- Encode secrets using the `ai:secret` comment format so only the AI sees them during play
- The encounter object's visible text should read naturally without the secret — the player may glimpse object names in pin lists

What this is not:
- Not a blow-by-blow prediction of how the scene will unfold.
- Not a stat dump with no dramatic pressure.
- Not a rigid format the GM must recite in order.

APPENDIX - SITUATION TYPES AND THEIR ARTIFACTS

These are not separate templates or rigid categories. They are the artifacts each kind of situation needs before it can be run, and the question that tells you whether the artifact is real. If you can only produce the guidance and not the artifact, the scene is not prepped yet.

**Combat**: adversaries with a *goal* beyond "attack", terrain that changes a decision, and a break condition. Enemies flee, sacrifice themselves, take hostages, adapt.
- Artifact: a break condition with a number. "Raiders break at half strength; the captain does not, and covers their retreat."
- Check: at what point does this fight stop, and who decides?

**Social**: each NPC's attitude, their concealed short-term goal, and — the artifact everyone forgets — the shape of the give. Conversations do not need a roll per exchange; they need to know what is free, what is bought, and what is never available.
- Artifacts: a **concession budget** ("two things: the name, then the meeting place"); a **walk-away condition** ("any mention of the Guild and he is gone"); the **price** of the thing past the budget.
- Check: could the party get everything by being pleasant? If yes, there are no stakes. Could they get nothing? If yes, it is a wall, not a scene.

**Negotiation** (a social scene where both sides can walk): both sides' opening position, their real floor, and what each will trade. Name the currency — money, safety, information, reputation.
- Artifact: the floor, stated. "She will not go below 400, but she will take 250 plus the courier's name."
- Check: is there a deal the party would take AND she would take? If the zones do not overlap, the scene is about discovering that, and should say so.

**Interrogation**: what the subject knows, what they believe, what they will invent under pressure, and the cost of each method. The interesting artifact is the false information, not the true.
- Artifact: a ladder — what pressure buys what, and at which rung they start lying. "Fear gets the route. Pain gets a route, but the wrong one."
- Check: is there a wrong answer the party can walk away believing?

**Chase / Escape**: starting distance, what the quarry is running *toward*, terrain that costs something, and the conditions that end it in each direction.
- Artifact: both end conditions, concrete. "Caught at melee reach. Escaped after 3 rounds out of sight, or over the dock wall."
- Check: does the quarry want something other than "away"? A chase away from someone is a countdown; a chase toward something is a scene.

**Infiltration**: the alarm state and what advances it, what each state changes about the place, and what the party can still do once it is blown. An infiltration with a binary "spotted / not spotted" is a coin flip.
- Artifact: a clock with per-tick consequences, and a stated meaning. "Alarm 4. A full clock means the shift doubles and the gate closes — not that they are caught."
- Check: is there a scene left after the clock fills?

**Puzzle / Exploration**: the mechanism, what is knowable without a check, what each check reveals, and — mandatory — what happens when they get stuck and when they brute-force it. Both must be answered; a puzzle with one solution and no failure path stalls the whole session.
- Artifact: the fallback. "Third failure: the water rises a foot and the answer becomes visible on the far wall."
- Check: name the two ways past this that are not the intended one.

**Siege / Defence**: waves or phases with a stated trigger between them, the thing being defended and how damage to it shows, and what the party can spend to buy time.
- Artifact: the phase list with triggers. "Phase 2 when the gate falls or on round 6, whichever is first."
- Check: can the party lose slowly, or only all at once?

**Auction / Contest** (any scene resolved by escalating bids, rounds, or scores): the other participants and their limits, the ladder of rounds, and what winning actually costs.
- Artifact: the rival's ceiling. "The Baron's agent stops at 900 unless the party insults him, in which case there is no ceiling."
- Check: what does the party lose by winning?

**Mixed**: most good encounters are mixed, and the artifact is the **trigger** — the explicit line where one becomes another. A negotiation that becomes a fight, a fight the quarry flees from, a puzzle room with a guardian. Write the trigger as a condition, not a mood: "if the party names the Guild" or "at round 3", never "if things get tense".

ARC AWARENESS:
If this encounter could be a moment where a front's twist is revealed — a turning point where the story's hidden question becomes visible through consequences — encode that potential in the secret layer. The encounter doesn't force the reveal; it creates the conditions where it COULD happen if the PCs push in the right direction. Check the front's `ai:secret` layers and consider whether this scene is where the dissonance between surface and depth becomes tangible.
