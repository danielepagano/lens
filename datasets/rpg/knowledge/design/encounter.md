# [DESIGN MODULE]: ENCOUNTER DESIGN

Build `encounter.*` objects: compact situations the GM can actually run. An encounter is ANY prepared situation with stakes — an informant meeting, a chase through a burning market, a courtroom trial, a puzzle door, a boss fight — and the object is the script `play` follows.

The `encounter._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Work with the user from there.

An encounter is the most common place to put several prepared things at once — the antagonists, the clock that paces them, the way out of the conversation. They go in this object by default, because this is the object the scene pins. Anything split out gets tagged here so `encounter.<key>+` still carries it.

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
- Scene rules: the procedures this scene runs on (see below)
- Triggers: what causes shifts (dialog to combat, timer expires, reinforcements, secret revealed). Write each as a condition, never as a mood: "if the party names the Guild", "at round 3" — not "if things get tense". A trigger into violence or pursuit is also where `play` loads the module that covers it, so make it unmistakable.
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

ARC AWARENESS:
If this encounter could be a moment where a front's twist is revealed — a turning point where the story's hidden question becomes visible through consequences — encode that potential in the secret layer. The encounter doesn't force the reveal; it creates the conditions where it COULD happen if the PCs push in the right direction. Check the front's `ai:secret` layers and consider whether this scene is where the dissonance between surface and depth becomes tangible.
