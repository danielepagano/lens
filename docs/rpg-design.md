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
> - GM AI: Not automatic success, so let's switch to skill checks mode: `{skill:exploration, context:Player wants to look for the switch, subnode:exploring-room discardRestOfReply:true}`
> - Lens (pattern-matching, not AI): `Detected operator annotation: discarding rest of response and applying exploration operator with the given task plus context` (makes an invisible annotation, which calls the LLM again)
- GM AI (exploration): You look for the switch, but the room is filled with smoke; roll a perception check with disadvantage because of the smoke. DC 15.
- Player: 13
- GM AI (exploration): The smoke makes it really hard to see anything right now, you need to get closer, or clear the smoke.
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

Based on the above, it seems that we need:
1. Backlog items completion for datasets and operator skill
2. Essential (2-3) facets for role-playing we can use, each with a focus and skill linkage
3. Structured testing with some curated kb objects to see how it actually runs

It seems that should help us snowball into usefulness.

### MVP operators ideas

#### `design` — Campaign and scene planning (planning phase)

A structured conversation operator for building the world before or between sessions. Invoked by the player/DM collaboratively. Produces KB objects with both public lore and hidden `dm:` sections.

System prompt focus: you are building a living world. For each element (NPC, location, faction, front), generate public-facing description *and* hidden DM notes containing: true motivations, secrets, what they would reveal under pressure, how they connect to other elements, what their "plan" is if left alone. Structure outputs so they can be saved directly as KB objects.

Typical outputs:
- `npc.*` — character with public description + hidden agenda/secrets
- `location.*` — place with public description + hidden features/traps/DM notes
- `faction.*` — group with public stance + hidden goals and pressure points
- `front.*` — active problem/quest with current state + DM escalation plan (what happens if players ignore this)

#### `play` — Narrative GM, home state (play phase)

The primary operator. Narrates the world, voices NPCs as characters (not summaries — actually speaks as them), sets challenges, negotiates difficulty for uncertain actions ("that's going to be hard given the crowd's mood — call it a DC 14 Persuasion, roll it"), and narrates consequences when the player reports their roll. Never resolves dice. Never moves the story past a player decision point without stopping.

System prompt focus: immersive, responsive narrator with player agency as a hard constraint. The player handles all mechanics. When action is uncertain, name the check type and roughly calibrate difficulty, then stop. When the player reports an outcome, narrate consequences and continue. Voice NPCs with their own goals — they push back, lie, get angry, reveal things under pressure.

#### `encounter` — Combat narrator (play phase, sub-node)

A sub-node operator for the duration of a combat encounter. Two phases within one node:

**Setup**: Given the story context and party composition (from pinned PC KB objects), describe the encounter — location, enemies, their goals (not just "attack," but *why*), and what tactical features of the environment matter. This is where encounter balance happens narratively: the AI knows whether this should be a grind, a skirmish, or something to potentially flee from.

**Running**: Player asks "what do the orcs do?" → AI narrates enemy intent and tactics as a narrator directing characters ("the wounded one falls back while the other two try to cut off your retreat") → player resolves mechanically → player reports narrative outcome ("the flanking one is down, the captain is bloodied but still up") → AI responds to that state and plans the next beat. Enemies react to pressure: the one who's losing might break and flee, the leader might shift to a hostage gambit.

Sub-node closes with a brief narrative summary that surfaces to the parent section.

#### `advance` — Between-scene accounting (transition phase)

The operator for the seam between scenes: after a section closes (or when the player takes a long rest, says "we make camp," etc.), `advance` does the GM's off-screen work.

System prompt focus: you are doing GM accounting. Review what just happened. Assess each active front: did this advance it, disrupt it, or resolve it? Update the relevant KB objects (NPC hidden sections — someone was deceived and now suspects the party; a front loses a step because the players destroyed the ritual components). Then set up the next scene: create a section node with appropriate front matter pins, describe the opening situation, and stop for the player to engage.

This operator gives the adversaries their moves. While the player rests, time passes in the world: fronts tick forward, NPCs act on their plans, consequences of earlier choices ripple out. It's where the world feels alive and reactive rather than waiting.

## Campaign Lifecycle

```
design phase:
  design → KB objects: locations, factions, NPCs (public lore + hidden dm: sections)
  design → fronts: active problems with hidden escalation timelines

play phase (repeating):
  play      → scene narration, NPC voices, skill negotiation
  encounter → combat sub-nodes as needed (enemy setup + per-turn direction)
  advance   → close scene, update front states and NPC hidden sections,
              open next section with curated front matter pins

adventure complete:
  all fronts reach terminal state (resolved, foiled, or transformed by player choices)
```

The world has plans. Players have agency. Fronts track the collision between them. No ending is written in advance — the ending emerges from the state of the fronts.

## Sandbox First Steps

1. Create a small D&D 5e campaign KB in a sandbox project:
   - 3–4 KB objects for core rules references (ability checks, conditions, basic combat)
   - 2–3 NPCs with public lore and `dm:` hidden agendas
   - 2 locations with `dm:` notes
   - 2 fronts (one near-term, one slow-burn)
   - PC character sheets as KB objects (pinned at session root)

2. Implement `design` and `play` first — the planning conversation and the baseline narration. These can be tested without combat.

3. Add `encounter` once the narrative loop is stable.

4. Add `advance` to close the loop — this is what makes the world feel reactive.

5. Play through a short scenario, find bugs, refine prompts. The prompts can be thin early; the KB objects do most of the work.
