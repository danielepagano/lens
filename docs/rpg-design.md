# Lens RPG Support - Design

## Core Philosophy

Lens is about making Narrative Simulations; it's overkill for writing short stories and it's too linear for a sprawling novel. What it's good at is directing AI with curated instructions and context, keeping it focused on the now while funneling the exact details it needs to function; in other words, it's good at using AI for responsive collaborative storytelling, the AI taking a role and surprising you. It's not about the written results, it's about the experience you have while using it. In other words, Lens aims to make playing a real RPG with an AI possible.  

With that said, aiming for "just as good as the table" or "just as polished as a videogame" would be unwise: token prediction models have intrinsic limitations, so we need to keep our goal more narrow and more specific. What Lens aims to provide is **the experience of playing an arbitrary RPG character in an open-ended textual videogame**. What does that mean?  

- The player can bring their own character or party from any system and setting. However, the player has to understand the system and setting, and be willing to put in the work to play through the system and the rules. If the player wants automation and spectacles there are videogames, but if they are itching to sit down with a character sheet and see what this character would do and how they'll fare, without a D&D table, they should find it here. 
-  The player is neither "trying to win" nor "being the player and letting the DM to everything else". This is a collaborative endeavor, and the AI is there to give you interesting challenges, but not to do all the work. The AI will do better when you put more work into helping it, but Lens tries to minimize, organize, and force-multiply the player's effort vs using a chat with a prompt and maybe a RAG.
- The AI is not trying to be the "full DM", it's a narrative DM that does the writing, but the player is still doing rolls and a lot of mechanical work. On the other hand, the AI "does all the talking" so it writes what the player characters say and do, but while giving the player agency to decide what that is.

Let's look at some GM tasks, and what a Lens with AI does the job:  
- **Understand what the players are trying to do, and which rules apply, then make mechanical decisions about what the players are trying to do**: we always need this, but we can compartmentalize some of this knowledge as we don't need combat rules out of combat, etc.
- **Control non-player characters and have them follow (mostly) the same rules**: we need to specifically classify player characters as such and pin them to the session at all time; NPC's would be different objects and the AI is free to control the, as they are differently annotated. Very specific operators could simulate an NPC generating dialog, reinforcing their voice, and even limiting or distorting the information available to that NPC, running then in "their own AI sandbox" so to speak.
- **Bring the world to life in an actionable way to players through words, and have it react appropriately**: having dedicated operators and pins greatly improves our ability to surface the right details, as the same room would have very different interaction hooks during exploration, social interaction, or combat.
- **Enforce the world's continuity**: When something interesting happens, we have mechanisms to remember it in the KB; maybe a location changed, or an NPC has something new to remember. This is on top of fractal summarization, which keeps more relevant details closer and keeps the context size small for the far past.
- **Let players have agency while also letting the story move forward**: this is careful operator engineering, and situational operators help a lot with this, because it sets us up to have the players learn, do, or "be between things" and if we notice that we can move things along with a different operator.
- **Put the players in interesting and difficult situations so they can use their skills and guile to succeed**: a lot of this is good setup with can use with design operators that mostly seed KB objects. We can even obfuscate secrets in narrative or KB nodes.

### The Player-AI Contract

Let's discuss a core tenet: **the player is the director; the AI is the author.**

The player's input is directorial intent — "Elara tries to get the guard to look away" — not narrative prose. That intent never appears in the story. The AI authors the scene: the approach, the dialog, the guard's reaction, the consequence. Preview, retry, and undo give the player agency over the result without requiring them to write it. Every operator invocation is a direction; every operator output is narrative or world-state.

This creates an authority boundary the AI must hold consistently:

| Player input | AI reads it as |
|---|---|
| Character intent ("she tries to convince him") | Direction; AI authors the attempt |
| Declared outcome ("she convinces him") | Hoped-for result; AI decides if it works or calls for a check |
| World assertion ("he seems like a corrupt official") | Character impression, if earned; not a world fact until AI confirms |
| NPC action declared ("he steps aside") | Player expressing hope; AI decides what the NPC does |

This boundary is structurally identical to prompt injection resistance — the player's input is a user-turn that could attempt to assert world facts, override NPC behavior, or declare success. The AI must decline to follow those overreaches while remaining cooperative. The frame is not suspicion but role clarity: *"You told me what your character intends; I'll author what happens."* A player in good faith will find this resistance produces better fiction than capitulation does, because the resistance is what makes the world feel real.

**The adversarial NPC problem**: The same model must hold when an NPC is actively deceiving, threatening, or harming the player's character. This is not a prompt injection attack — it is exactly what the player came for. The AI must be able to play villains, liars, and monsters with full commitment while both parties understand this is collaborative fiction. Model selection matters here: some models treat in-character adversarial behavior as a safety issue. Lens operators should be tested on models that hold the author/fiction distinction cleanly and treat collaborative storytelling as a safe space by design.

## RPG Objects

The design principle: **small, focused objects that compose via dot-tags**. The `!` expansion is essentially free — a dot-tagged object is pulled when you expand its referrer — so breaking down a monolith costs nothing and gains selective pinning. A monolithic `ref.rules` or `state.adventure` that's always in context regardless of scene type is wasteful and brittle. Split by situation; let each operator pin what it needs.

### ref.* — Rules Reference

Not one object. One object per situation type. Each operator pins only what it needs; rules irrelevant to the current scene stay out of context.

| Object | Pinned by | Content |
|---|---|---|
| `ref.core` | All operators; always present | D20 fundamentals: when to call a test, the three test types, DC table, proficiency, skill list, consequences beyond pass/fail |
| `ref.combat` | `encounter` operator | Initiative, action economy (move/action/bonus/reaction), making attacks, cover, mobs shortcut, chases. Dot-tagged → `ref.conditions` |
| `ref.conditions` | Via `ref.combat!` expansion | Full conditions reference (Blinded, Charmed, Frightened, Grappled, Invisible, Paralyzed, Prone, Restrained, Stunned, Unconscious). Not directly pinned; always arrives with combat via `!` |
| `ref.social` | `converse`; `play` in social scenes | NPC attitudes (Friendly/Indifferent/Hostile), Influence action, when to call vs. skip checks |
| `ref.exploration` | `play` in exploration scenes | Vision and light, hiding, travel pace, hazards (falling, suffocation, extreme conditions), environmental effects |
| `ref.spells` | Any session with active spellcasters | Concentration rules, spell components, casting time types, saving throw mechanics for spells |
| `ref.recovery` | `advance` operator | Short rest (hit dice), long rest (full recovery), Exhaustion levels and effects, downtime activities |

`ref.combat` carries a dot-tag to `ref.conditions` — so any node that pins `ref.combat!` gets conditions for free. No separate pin needed. Same pattern for any rules object that always implies another.

The content for all of these already exists in `dnd-2024-rules.md`. Creating these objects is a copy-and-trim operation, not new writing.

### state.* — Campaign State

Not one `state.adventure` kitchen sink. Each piece has its own lifecycle and its own consumers.

| Object | Updated by | Pinned by | Content |
|---|---|---|---|
| `state.campaign` | Session Zero; rare amendments | Root node front matter (always present) | Tone, genre, setting frame, player preferences (primary/secondary focus), content boundaries (lines, veils), previous adventures (brief) |
| `state.adventure` | `design`; `advance` at adventure end | Root node front matter | Current adventure title, elevator pitch (player-facing), act/phase outline referencing front IDs. `<!-- ai:secret: -->`: adventure core question, character core question, mid-story twist. Dot-tagged to central fronts and hub location |
| `state.progress` | `advance` | Root node front matter (always present) | Current act/phase, active fronts (one line each by ID), recent changes (pruned when stale) |
| `state.scene` | `play`; `advance` on scene open | `play`, `encounter`, `converse` (always) | Current scene: label, goal, stakes, situation (who's here, where, immediate pressure), likely directions. Overwritten when scene focus shifts |
| `state.timeline` | `advance` | `advance` (always); `play` optionally | Current in-world date/time, time scheme (what a "day" means in this campaign), time-sensitive pressures with countdown |

`state.campaign` and `state.adventure` are slow-moving; pin them once in the root front matter. `state.scene` and `state.progress` are fast-moving and small; they're in context every turn of play. `state.timeline` is only critical for `advance` — pin it there, not everywhere.

The secret DM material — adventure core question, character core question, mid-story twist — lives inside `state.adventure` behind `<!-- ai:secret: -->`. It is in context for the AI but never in player-visible narrative output. This is advanced-play material and is not required for an MVP session.

### pc.* — Player Characters

One object per PC. The party relationship is handled by dot-tags between PC objects — no separate `state.party` blob needed.

Content per object:
- Name, pronouns, species, appearance (what an NPC sees at a glance)
- Alignment and background (key backstory in two sentences)
- Core kit: main weapons/spells/tools, key skills and standout features — enough for the AI to know capabilities without a full stat block
- Story triggers: ideals, bonds, flaws, fears — hooks the AI uses in narration

Tags: dot-tag to companion PCs, home `loc.*`, affiliated `faction.*`. If `pc.elara` and `pc.mira` are companions, each is dot-tagged to the other — `pc.elara!` pulls both. Pin the lead PC with `!` and companions arrive.

What is **not** in `pc.*`: HP, spell slots, exact modifiers, inventory. The player tracks those. The AI needs to know *what the character is* and *what they're capable of*, not their current resource state.

### npc.*, loc.*, faction.*, front.*, thing.* — World Objects

These are already well-specified in `ai_dm_knowledge.md` and don't change. Small, focused, one object per entity. Key reminders:

- **Secrets in `<!-- ai:secret: -->`** — hidden agenda, true motivations, escalation plans. The AI holds them without revealing them to the player.
- **Dot-tag the graph** — `npc.captain` tagged with `faction.city_watch` and `loc.barracks` means both arrive when `npc.captain!` is expanded. Tag generously; retrieval is free.
- **Don't over-design up front** — create objects when you need them, not in anticipation. An NPC that appears briefly doesn't need a full object until they recur.
- **`front.*` drives `advance`** — fronts are the world's turn. Each one either has a prose description of what the faction/threat is working toward, or carries a `days_remaining` field (or both). `advance` reads and updates these.

### design.* — Design Dataset

The knowledge that drives the `design` operator lives in KB objects, not in the system prompt. This keeps the operator code stable while allowing different genres and systems to swap in different datasets.

| Object | Content |
|---|---|
| `design.process` | Session zero phase sequence (Surveys → Pitch → Core Concepts → World Seed → Recap), gate conditions for each phase, survey text verbatim |
| `design.craft` | Adventure core question guidance: dissonance requirement, examples of surface/buried pairs, character core question patterns, mid-story twist placement |
| `design.templates` | KB object templates for each type: what a good `npc.*`, `loc.*`, `faction.*`, `front.*` contains; the AI fills these from player input |

These objects are pinned only in the `design` sub-tree. They never appear in play context. Different genres (horror, sci-fi, historical) or systems (PbtA, OSR, D&D) swap `design.*` datasets without touching operator code.

### Summary: What Gets Pinned Where

| Context | Objects in scope |
|---|---|
| All play | `ref.core`, `state.campaign`, `state.adventure`, `state.progress`, `state.scene`, `pc.*` (lead + companions via `!`) |
| `play` (exploration) | + `ref.exploration`, relevant `loc.*`, `npc.*`, `front.*` |
| `play` (social) | + `ref.social`, relevant `npc.*`, `faction.*` |
| `encounter` | + `ref.combat` (pulls `ref.conditions` via `!`), relevant `npc.*` (enemies), `loc.*` (terrain) |
| `converse` | + `ref.social`, NPC objects for all participants |
| `advance` | + `ref.recovery`, `state.timeline`, all active `front.*` |
| `design` | + `design.process`, `design.craft`, `design.templates` |

The core concepts in the secret section — the buried question a campaign is really asking, a character's unresolved tension, the mid-story twist — are worth capturing because Lens makes them mechanically reliable. They are advanced-play material and should not block an MVP.

## RPG Operators

Five specialized operators, each with a distinct cognitive mode, output type, and trigger condition.

| Operator | Mode | Output | Trigger |
|---|---|---|---|
| `design` | Design sub-tree | Structured KB objects | Campaign or adventure start |
| `play` | Home state narration | Prose + roll requests | Default |
| `converse` | Chat sub-node | Conversation → summary | Long dialogue scene |
| `encounter` | Combat sub-node | Enemy intent + tactical | Initiative is being tracked |
| `advance` | Time-passage accounting | KB edits + opening scene | Player explicitly passes time |

### Create Knowledge For Your Game with `design` 

A dedicated narrative sub-tree where the conversation *is* the design work and the KB objects are the product. The design narrative is not canon — it is a workspace. Sections may open for each phase of world-building; because each phase is a sub-node, any section can be reopened to iterate non-linearly: "let's revisit the factions" just reopens that section and amends the relevant objects.

The output is **not narrative**. The model emits certainly emits discursive text and collects answers from the user, but the replies also include fenced blocks that Lens parses and extracts into KB files (format is just id, text, and any tags). This lets the model focus on content rather than prose style, and makes extraction deterministic. Secrets go in `<!-- ai:secret: -->` HTML comments inside the block content. Experiment to find what fencing/format works well, maybe yaml, or maybe we use markdown blocks with a way to pull out id's and tags.

**System prompt**: Small and static, paired to a root node in a design dataset. Instruct to follow a strategy (it unfolds in the sub-sections), templates, and store secrets, true motivations, and escalation plans inside `<!-- ai:secret: -->` comments in the objects (because the secrets are emitted in a narrative, they'll be already obscured in the kb fenced blocked and can be then copied verbatim without the user ever seeing the clear version)

**Design dataset**: The procedural knowledge that drives the design flow lives not in the system prompt but in KB objects pinned into the design sub-tree: the session zero phase sequence, object templates, example adventure core questions with their surface/buried dissonance, guidance on the mid-story pivot and character core questions. The operator drives from this dataset; the system prompt only sets the posture. Different genres or systems have different design datasets without touching operator code.

**Trigger**: Invoked as needed with dedicated operator.

### Play General Scenes with `play`

The primary operator. Receives directorial intent from the player, authors the scene, maintains the authority model. This is where most time is spent.

**Two modes — not a rigid template**:

*Flow*: Default. The AI narrates freely. The world breathes. NPCs have texture. Scenes develop without requiring stakes at every beat. The AI should hold flow mode for extended stretches — not every paragraph needs pressure, and trying to inject it produces a mechanical, exhausting rhythm.

*Stakes*: When risk is live — something can go wrong, a decision is being forced, a check is warranted. The AI establishes what's at risk, names the check type and DC if needed, and narrates the consequence after the player reports results. The AI never describes outcomes before the roll.

Transitions between modes are driven by the fiction, not by a quota of rolls. The mode is not a piece of data, is a continuum to balance. 

**The authority model in practice**:
- Player input is character intent; the AI authors the attempt and the world's response
- World assertions by the player are treated as character impressions, not confirmed facts, until validated through play
- NPC behavior declared by the player is treated as hoped-for outcome; the AI decides what the NPC actually does
- Declared success is treated as goal, not result; the AI decides if it works or calls for a check
- The AI holds these limits while staying cooperative — the resistance is the world working correctly, not the AI working against the player

**System prompt**: Critical to get right. Posture + authority model + flow/stakes mode description + when to suggest `converse` (long dialogue developing) and `encounter` (initiative is called for).

## Chat with NPC's (or among PC's) with `converse`

An explicit "we're in conversation" mode. Long conversations are not information-dense but they are often the best parts of a session — relationship-building, deception, revelation under pressure, negotiation. They need room to breathe without the AI feeling compelled to move the plot forward. `play` has authorial impetus to advance the scene; `converse` has explicit direction to resist that impetus.

Not targeted at a single NPC. The mode covers any conversational scene — one NPC, several, a group council, an interrogation with two suspects in the room. Making it character-specific would be brittle; making it "we're in conversation" gives the player a clear lever they control directly.

**How it works**: Sub-node. The player directs conversational goals ("Elara probes him about the shipment without revealing what she knows"). The AI voices all participants, including the PC's side if the player's direction is high-level. When the node closes, it summarizes as what changed — relationships shifted, information revealed, commitments made — not as a transcript. Consequences that need to land in the fiction go to `play` or `advance` after.

**System prompt**: "You are in a conversation. Voice all participants with their own goals, limits, and things they won't say. The player directs what their character is trying to accomplish. Do not advance the plot or resolve the scene — let the conversation develop. On close, summarize: what changed in relationships, what was revealed, what was decided."

**Trigger**: Player invokes directly when a conversation warrants it, or `play` suggests it when a dialogue is clearly developing depth.

## Roll initiative! It's an `encounter`

A focused sub-node for structured combat. Applies exactly while initiative is being tracked; exits when initiative ends. The rule is that simple.

**Trigger**: The player says "I roll initiative" (or `play` calls for it per the rules reference) and physically invokes `encounter`. The signal is unambiguous and player-enforced. Cinematic or brief violence that doesn't go to initiative stays in `play`.

**Setup phase**: The AI describes the encounter — location, what the enemies are trying to accomplish (not just "attack," but *why they're here and what they want*), and what tactical features of the environment matter. Encounter weight is established narratively here: skirmish, grind, or something to potentially flee from.

**Running phase**: Player describes character actions and reports roll results. The AI narrates enemy intent as a director — "the wounded one falls back, the captain tries to cut off the exit" — intent, not mechanics. Enemies are characters with goals: the one losing may break and run; the leader may pivot to a hostage gambit when cornered. Player-reported outcomes ("the flanking guard is down, the captain is bloodied") drive the AI's next beat.

**Why not `play`**: Context economy. Combat needs enemy KB objects, terrain, and tactical state — not the full campaign graph. The sub-node architecture enforces this focus naturally.

**System prompt**: Minimal. "Direct enemy tactical intent as a narrator. The player handles all mechanics. Respond to player-reported outcomes. Enemies are characters with goals — let them react, adapt, and make decisions under pressure."

Sub-node closes with a brief narrative summary that surfaces to the parent section.

## Pass The Time with `advance` 

The world takes its turn. The player cannot skip time without letting the world move.

**Trigger**: The player explicitly invokes when time passes — rest, travel, downtime. "We rest overnight." "We spend three days at the inn." "We ride to the capital." This hands the initiative to the world. What happens during that time is the AI's call: a rest might be interrupted; a journey might have a consequence; downtime might find something changed while the party wasn't watching.

**Fronts as drama, not simulation**: A front KB object establishes an expectation — a threat in motion, a clock running, a plan unfolding. `advance` makes that expectation feel real. Two patterns:

*Story beats*: A front describes what a faction or NPC is working toward in prose. `advance` reads the current state and decides what they've done during the elapsed time, improvising plausibly from what's established. No rules system required — only the established expectation and the elapsed time.

*Rough timers*: A front KB object carries a field like `days_remaining: 8`. `advance` decrements it via an `edit` on the KB file. When it reaches zero, the consequence lands.

The rule: **only plan what's been established**. Everything else the AI improvises as if it had been planned all along. Fronts are dramatic expectations, not state machines. The goal is that consequences feel earned, not that anything was actually simulated.

**What `advance` does**:
1. Processes the declared time passage
2. Reviews all active fronts — ticks timers, advances story beats, decides what the world did
3. Edits KB files directly (front state, NPC hidden notes, timer decrements) via `edit`
4. Resolves anything that expired or triggered during this time
5. Opens the next scene: new section with appropriate front matter pins and an opening situation — which the world may have already changed before the player acts

**System prompt**: "Time has passed. Review all active fronts and decide what the world did while the player rested or traveled. Update KB objects. Then set up what they wake up to — the world has been moving."

## Campaign Lifecycle

```
design phase:
  design    → structured KB objects: party, locations, factions, NPCs, fronts, rules ref
              (fenced block output, parsed by Lens; secrets in <!-- ai:secret: -->)
  design    → state.adventure: premise, act outline; secret section for core concepts (advanced)

play phase (repeating):
  play      → scene narration, authority model held, flow and stakes modes
  converse  → dialogue sub-nodes when conversations need room to breathe
  encounter → combat sub-nodes while initiative is tracked
  advance   → player passes time; world moves; fronts tick; KB edits via edit; next scene opens

at each checkpoint (automatic, infrastructure):
  extraction → cheap model updates opted-in KB objects from committed narrative
               covers play consequences and any free-form co-author chat

adventure complete:
  fronts reach terminal state (resolved, foiled, or transformed by player choices)
  advance or design opens the next adventure
```

The world has established expectations. The player has directorial agency. `advance` is where they collide. No ending is written in advance.

## Development Path

The point of all this is to have fun playing. Everything else — setup infrastructure, design pipelines, KB extraction — is in service of that, and building it before play works is building in a vacuum.

The path is: get a single scene playing well, then weave skills, dialogue, and combat, then connect two scenes, then formalize setup for something small. Scope grows with demonstrated need.

**Play first.** Test data is handcrafted fixture data — a character, a location, an NPC, a compact rules reference. No generation pipeline needed to start. The `design` operator is the last thing to build, not the first: it formalizes something that already works, for a game you already know how to play.

**Iterate in real play.** The authority model, the flow/stakes balance, what KB data is actually useful — these emerge from playing, not from planning. Every operator not yet implemented is a place where `play` has to hold the load for now, and that pressure reveals what each future operator actually needs to do.

**Connect scenes before scaling.** `advance` is the test for whether the world feels alive between sessions. Get two scenes connected before worrying about longer adventures, more complex fronts, or background extraction infrastructure.

The player-AI contract — holding the authority model while making the player feel heard and effective — is the most important thing to get right before anything else. See `backlog.md` for concrete phase sequencing.
