# Lens RPG Support - Design

## Why, What, and What Not

Lens is about making Narrative Simulations; it's overkill for writing short stories (unless you want to squeeze everything you can from 9k tokens), and it's too linear for a sprawling novel. What it's good at is directing AI with curated instructions and context, keeping it focused on the now while funneling the exact details it needs to function; in other words, it's good at using AI for responsive collaborative storytelling, the AI taking a role and surprising you. It's not about the written results, it's about the experience you have while using it. In other words, Lens aims to make playing a real RPG with an AI possible.  

With that said, aiming for "just as good as the table" or "just as polished as a videogame" would be unwise: token prediction models have intrinsic limitations, so we need to keep our goal more narrow and more specific. What Lens aims to provide is **the experience of playing an arbitrary RPG character in an open-ended textual videogame**. What does that mean?  

- The player can bring their own character or party from any system and setting. However, the player has to understand the system and setting, and be willing to put in the work to play through the system and the rules. If the player wants automation and spectacles there are videogames, but if they are itching to sit down with a character sheet and see what this character would do and how they'll fare, without a D&D table, they should find it here. 
-  The player is neither "trying to win" nor "being the player and letting the DM to everything else". This is a collaborative endeavor, and the AI is there to give you interesting challenges, but not to do all the work. The AI will do better when you put more work into helping it, but Lens tries to minimize, organize, and force-multiply the player's effort vs using a chat with a prompt and maybe a RAG.

So, what are trying to have the AI _actually do_?  

- Understand Role Separation: the player has to have agency, and not by being able to tell the AI what to do, but by allowing their characters to have agency in the story. The AI has to be extremely constrained in what they write about a player character thinking or doing while not being a pushover (in fact, pushing back in an interesting way) about anything else. 
-  Be ontologically consistent: token prediction models can be easily pushed to hallucinate, and too quickly drown in irrelevant details. Lens' architecture is an exercise in dramatically sharpening focus to where it matters (hence the name). In earlier attempts at doing this, the author designed the knowledge store and then cajoled the AI to run some python before every response to get tool output of current state inserted into context... this was both slow and error-prone. With Lens, we can deterministically feed knowledge, control how much detail about the past is relevant, and even use operators to not only reply to a chat, but to trigger specific behaviors (completely different system prompts for the same context) or run any python code, etc.

## Modalities and meta-cognition

As AI tools evolved to get work done, we saw the rise of tools, skills, MCP servers, and sub-agents. These are all methods to give the AI "teeth" (let them affect the world, let them gather specific information) and "focus" (inject sub-prompts to get things done, break down scope and attention to sub-tasks). The main chats becomes more of an orchestrator, and the system has several self-correcting features, like external validation (e.g. running linting and tests after the code is written). 

When running an RPG, the GM similarly has to leverage several mental tools, like:  
- Understand what the players are trying to do, and which rules apply
- Make mechanical decisions about what the players are trying to do
- Control non-player characters and have them follow mostly the same rules
- Bring the world to life in an actionable way to players through words, and have it react appropriately
- Enforce the world's continuity
- Let players have agency while also letting the story move forward
- Put the players in interesting and difficult situations so they can use their skills and guile to succeed

In a videogame, all these problems are solved by designers and artists well in advance by creating rule systems, writing stories, and managing world state. However these a-priori decisions have a strong responsiveness limit: you have to play a certain story with certain paths. While a single long prompt could try to do all of the above all the time, in practice most of them have a time and place where they matter most, and we have only so much attention and tokens we want to burn at any given time, so we need to make choices. 

GM's can also use actual tools to get things done, like dice rolls, rule references, encounter balancing tools, maps, clocks, trackers, etc. None of these are _really_ why a game is fun, but they can help smooth out the consistency curve and let the player focus more on the fun parts. Once again, these are quite circumstantial: could be critical in combat, but not at other times.

### Tools and sub-agents

So, much like a code-writing AI can choose tools, we want our GM AI to reason about what we are doing, and then use the right prompt, details, and tools to get the job done. Sure the player could say "hey this is exploration, ask me to do a perception check" but it should be feasible for an AI that is _specifically looking for what mental tools applies_ to also notice this, and ask for perception checks. So we can have a set of possible sub-agents that have specific prompts and maybe access to specific reference or code tools, and call them that way.

- Player: I look for the switch
> - GM AI: `<thinking>` the player wants to find the switch, but the room is filled with smoke; this is difficult, so I'll have to make a ruling... let me ask the rules AI with this prompt "how hard is to see a small switch in a room filled with smoke?"`</thinking>` 
>     - Rules AI: that's a perception check with disadvantage because of the smoke; they would need to beat a DC 15 to see a small switch that's not specifically hidden
- GM AI: `<thinking>`I see. Ok I know what to do.`</thinking>` Roll perception with disadvantage.
- Player: 13
- GM AI: `<thinking>`Based on what the rules AI says, 13 is too low; they fail, but I should guide them forward in a helpful way as usual.`</thinking>` The smoke makes it really hard to see anything right now, you need to get closer, or clear the smoke.
- Player: Roy casts Wind Gust
- ...the GM AI would then have to ask the rules AI about what the spell does, determine results, etc...

That's too slow/overly elaborate for a simple perception check, but we can see that the rules tool does not need a large request, nor has to be particularly smart: it needs a rules reference, but could use a RAG or even a free-text search and rather basic thinking to get an answer: the point is that it doesn't distract the main GM and burns context. When the rules are more complex or data-heavy, like "how does this spell work in this circumstance" this would be even more effective. 

### Lens: Sequential agents instead of tools/sub-agents

Now with Lens, we can do something different than that, because we have sub-nodes. So instead of using thinking mode and going back and forth, we instead hand off the job to another agent in a sub-content, still with different abilities and goals, but directly in charge. We could also use thinking mode, but we try not so we can go faster/cheaper. So the above interaction would work as follows (quoted items do not produce visible output):

- Player: I look for the switch
> - GM AI: Not automatic success, so let's switch to skill checks mode: `{play:explore-room, prompt:Player wants to look for the switch, discardRestOfReply:true}`
> - Lens (pattern-matching, not AI): `Detected operator annotation: discarding rest of response and applying exploration operator with the given task plus context` (makes an invisible annotation, which calls the LLM again)
- GM AI (play): You look for the switch, but the room is filled with smoke; roll a perception check with disadvantage because of the smoke. DC 15.
- Player: 13
- GM AI (play): The smoke makes it really hard to see anything right now, you need to get closer, or clear the smoke.
- Player: Roy blows into his palm to summon a gust of wind @spell.wind.gust
> Lens: detected KB lookup. spell.wind.gust matches an object ID in the D&D dataset, so I'm going to include that KB item together with the rest of the message
- ...the AI now has both exact spell description and flavor, so it can determine that it would work to clear smoke, but also it alerts nearby enemies to their presence, etc...

The main philosophical difference here is that in the first example, the sub-agent is providing a specialized reference service, working like a tool that returns to the caller, and in the second case the tool call triggers a re-facet of the GM AI with a different focus, chaining it to the first; the new facts has a reference guide about resolving skill checks and engages with the user in a kind of task (like exploration, dialog, combat, etc), maybe dropping other instructions about different situations (while knowing they exist so they can switch facet later). This reduces invocations and maintains continuity with a shared GM core all the facets share. Also, because we are using Lens to chain the operators dynamically, we're effectively creating an agentic loop, and we could do fun stuff like an GM asking an NPM to say something, and Lens recognize that's a sub-operation and it should resume the previous operator after, so the GM can continue writing; as long as we don't use thinking mode and keep the context of these nested operator quite small (general context, audience, task, npc details, and relevant knowledge they are talking about), this could create an experience that's both engaging for the user and cheap to run context-wise.

When casting the spell, the AI could have detected that like in the first case and emitted "I don't know spells, I need a skill" etc. but it could have also not noticed, or hallucinated a spell. By embracing the "game" part of the system and having the user set a pin (with @ in the string or --pin in the CLI, or something else, whatever is easier and auto-completes!) instead of just doing loose conversation, Lens performs a very fast and reliable look-up, so the player can be confident that the AI knows _exactly_ what their spell does and will adjudicate results correctly, even if the player added flavor and distractions. Over time we can fine-tune how much explicit pinning VS tool look-ups VS other non-AI heuristics works well/is fun, but a simple auto-completing pin UX may be one of the simplest, most effective things we can do. 

Let's look at the list of GM tasks above, how it could be solved with Lens:  
- Understand what the players are trying to do, and which rules apply: we always need this, but at pretty coarse level of which kind of rules apply
- Make mechanical decisions about what the players are trying to do: we can delegate to either sub-agent "judge" or switch facet to resolve more complex rules
- Control non-player characters and have them follow mostly the same rules: we need to specifically classify player characters as such and pin them to the session at all time; NPC's would be different objects and the AI could easily "hand off" control to an operator that is talking as an NPC with a goal, even limiting or distorting the information available to that NPC: running NPCs in "their own AI sandbox" needs testing but could be quite fun and effective
- Bring the world to life in an actionable way to players through words, and have it react appropriately: having facets greatly improves our ability to surface the right details, as the same room would have very different interaction hooks during exploration, social interaction, or combat.
- Enforce the world's continuity: we can use tasks for side-effects, not results! When something interesting happens, the AI can just emit a task to remember it in the KB; maybe a location changed, or an NPC has something new to remember. The task can be very generic, and we can then spin another LLM (even in the background if we want) to analyze what changes from the perspective of an object and see what needs to be stored.
- Let players have agency while also letting the story move forward: facets help a lot with this, because it sets us up to have the players learn, do, or "be between things" and if we notice that we can move things along with a different facet.
- Put the players in interesting and difficult situations so they can use their skills and guile to succeed: very specific playbooks could be prepared for this, and they could be invoked at specific times for planning; the plans can be in the KB so they can be surprising! Nothing stops us from encrypting (or just ROT16ing) certain KB nodes so it's a pain in the butt for players to peek at plans (or avoids them accidentally seeing something)

And remember, KB items are markdown and templated, nothing prevents us from having them contain structured data plus instructions: they can literally be mini-DBs if we want to!
Being able to leverage the KB as well as operators really gives us a rich toolset of tools we can define: expand dice roll annotations on receipt, inject rule references, facets for encounter balancing that can even add up CRs for us and such, maybe use known details to generate battle maps (image or procedural), track fronts and clocks in KB, etc.

# The Core Lens RPG MVP

## The Player-AI Contract

Before designing operators, the foundational model: **the player is the director; the AI is the author.**

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

## How KB Objects Get Updated

Two paths, no dedicated KB write primitive:

**`design` output is parsed structurally.** The model emits fenced blocks (YAML or similar) that Lens extracts mechanically into KB files — no tool call, no runtime primitive. The output is not narrative and is optimized for machine parsing, not prose style.

**Everything else uses `edit` targeting a KB file.** The `edit` operator already handles targeted AI mutation with a full transaction/diff/review cycle. Pointing it at a KB file rather than a narrative node is sufficient — more controllable than a dedicated primitive, and the user triggers it explicitly. `advance` uses this for front and NPC updates; the background extraction infrastructure uses it at checkpoint.

Hidden sections inside KB objects use HTML comments: `<!-- ai:secret: ... -->`. Lens ROT13-encodes them on write, making them non-obvious to casual readers while remaining decodable for GM-mode operators. Public content sits above; secrets sit in the comment:

```markdown
The mining consortium is running behind on the ore contract.

<!-- ai:secret:
True situation: three miners died in a cover-up six weeks ago. The foreman
will do anything to prevent discovery. Escalation: arrest threats → arson →
hired violence. Days until the consortium's inspector arrives: 8.
-->
```

Mid-campaign world amendments (what `lore` would have handled) are just free chat — the background extraction infrastructure picks up whatever is worth keeping at the next checkpoint.

## Operator Overview

Five operators, each with a distinct cognitive mode, output type, and trigger condition.

| Operator | Mode | Output | Trigger |
|---|---|---|---|
| `design` | Session Zero sub-tree | Structured KB objects | Campaign or adventure start |
| `play` | Home state narration | Prose + roll requests | Default |
| `converse` | Chat sub-node | Conversation → summary | Long dialogue scene |
| `encounter` | Combat sub-node | Enemy intent + tactical | Initiative is being tracked |
| `advance` | Time-passage accounting | KB edits + opening scene | Player explicitly passes time |

## `design` — Session Zero Sub-Tree

A dedicated narrative sub-tree where the conversation *is* the design work and the KB objects are the product. The design narrative is not canon — it is a workspace. Sections open for each phase of world-building; because each phase is a sub-node, any section can be reopened to iterate non-linearly: "let's revisit the factions" just reopens that section and amends the relevant objects.

The output is **not narrative**. The model emits structured fenced blocks that Lens parses and extracts into KB files. This lets the model focus on content rather than prose style, and makes extraction deterministic. Secrets go in `<!-- ai:secret: -->` HTML comments inside the block content.

**System prompt**: Small and static. "You are building a living world. Follow the design dataset. Emit each element as a fenced YAML block with the object ID as a header. Put secrets, true motivations, and escalation plans inside `<!-- ai:secret: -->` comments — never expose these to the player."

**Design dataset**: The procedural knowledge that drives the session zero flow lives not in the system prompt but in KB objects pinned into the design sub-tree: the session zero phase sequence, KB object templates for each type, example adventure core questions with their surface/buried dissonance, guidance on the mid-story pivot and character core questions. The operator drives from this dataset; the system prompt only sets the posture. Different genres or systems have different design datasets without touching operator code.

**What design produces**:
- `pc.*` — party members with appearance, kit summary, and story triggers
- `npc.*`, `loc.*`, `faction.*`, `front.*` — world elements with public lore and `<!-- ai:secret: -->` hidden sections
- `ref.rules` — compact rules reference for the system being played
- `state.adventure` — campaign premise, tone, modes, act outline; secret section carries core concepts (adventure core question, character core question, mid-story pivot) for advanced play scenarios

The core concepts in the secret section — the buried question a campaign is really asking, a character's unresolved tension, the mid-story twist — are worth capturing because Lens makes them mechanically reliable. They are advanced-play material and should not block an MVP.

**Trigger**: Invoked once at campaign start and again at the start of each new adventure.

## `play` — Home State

The primary operator. Receives directorial intent from the player, authors the scene, maintains the authority model. This is where most time is spent.

**Two modes — not a rigid template**:

*Flow*: Default. The AI narrates freely. The world breathes. NPCs have texture. Scenes develop without requiring stakes at every beat. The AI should hold flow mode for extended stretches — not every paragraph needs pressure, and trying to inject it produces a mechanical, exhausting rhythm.

*Stakes*: When risk is live — something can go wrong, a decision is being forced, a check is warranted. The AI establishes what's at risk, names the check type and DC if needed, and narrates the consequence after the player reports results. The AI never describes outcomes before the roll.

Transitions between modes are driven by the fiction, not by a quota of rolls. Many good scenes never roll anything.

**The authority model in practice**:
- Player input is character intent; the AI authors the attempt and the world's response
- World assertions by the player are treated as character impressions, not confirmed facts, until validated through play
- NPC behavior declared by the player is treated as hoped-for outcome; the AI decides what the NPC actually does
- Declared success is treated as goal, not result; the AI decides if it works or calls for a check
- The AI holds these limits while staying cooperative — the resistance is the world working correctly, not the AI working against the player

**System prompt**: Small and static. Posture + authority model + flow/stakes mode description + when to suggest `converse` (long dialogue developing) and `encounter` (initiative is called for).

**Near-permanent KB pins** (via ancestor front matter, not the system prompt):
- `pc.*` — party objects
- Active `front.*` objects
- `ref.rules` — compact rules reference
- Current `loc.*` — active location

These flow in automatically through the pin hierarchy. The system prompt does not carry world state.

## `converse` — Chat Sub-Node

An explicit "we're in conversation" mode. Long conversations are not information-dense but they are often the best parts of a session — relationship-building, deception, revelation under pressure, negotiation. They need room to breathe without the AI feeling compelled to move the plot forward. `play` has authorial impetus to advance the scene; `converse` has explicit direction to resist that impetus.

Not targeted at a single NPC. The mode covers any conversational scene — one NPC, several, a group council, an interrogation with two suspects in the room. Making it character-specific would be brittle; making it "we're in conversation" gives the player a clear lever they control directly.

**How it works**: Sub-node. The player directs conversational goals ("Elara probes him about the shipment without revealing what she knows"). The AI voices all participants, including the PC's side if the player's direction is high-level. When the node closes, it summarizes as what changed — relationships shifted, information revealed, commitments made — not as a transcript. Consequences that need to land in the fiction go to `play` or `advance` after.

**System prompt**: "You are in a conversation. Voice all participants with their own goals, limits, and things they won't say. The player directs what their character is trying to accomplish. Do not advance the plot or resolve the scene — let the conversation develop. On close, summarize: what changed in relationships, what was revealed, what was decided."

**Trigger**: Player invokes directly when a conversation warrants it, or `play` suggests it when a dialogue is clearly developing depth.

## `encounter` — Combat Sub-Node

A focused sub-node for structured combat. Applies exactly while initiative is being tracked; exits when initiative ends. The rule is that simple.

**Trigger**: The player says "I roll initiative" (or `play` calls for it per the rules reference) and physically invokes `encounter`. The signal is unambiguous and player-enforced. Cinematic or brief violence that doesn't go to initiative stays in `play`.

**Setup phase**: The AI describes the encounter — location, what the enemies are trying to accomplish (not just "attack," but *why they're here and what they want*), and what tactical features of the environment matter. Encounter weight is established narratively here: skirmish, grind, or something to potentially flee from.

**Running phase**: Player describes character actions and reports roll results. The AI narrates enemy intent as a director — "the wounded one falls back, the captain tries to cut off the exit" — intent, not mechanics. Enemies are characters with goals: the one losing may break and run; the leader may pivot to a hostage gambit when cornered. Player-reported outcomes ("the flanking guard is down, the captain is bloodied") drive the AI's next beat.

**Why not `play`**: Context economy. Combat needs enemy KB objects, terrain, and tactical state — not the full campaign graph. The sub-node architecture enforces this focus naturally.

**System prompt**: Minimal. "Direct enemy tactical intent as a narrator. The player handles all mechanics. Respond to player-reported outcomes. Enemies are characters with goals — let them react, adapt, and make decisions under pressure."

Sub-node closes with a brief narrative summary that surfaces to the parent section.

## `advance` — Time Passage

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
