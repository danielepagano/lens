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

### Planning VS Play

The key design impetus of Lens is to curate and constrain the knowledge set and instructions given to the AI, so it can behave predictably without bloating the context window. Hierarchical summarization makes this already possible with just a bit of user discipline with sections, but when running D&D we have both a large ruleset (baseline knowledge corpus) and demand more from the AI in terms of prompt compliance. We therefore need all the tricks we can to keep context and prompts small and focused.

To this extent, we divide our experience in two alternating phases:  
  - **Planning**: during planning we don't directly generate narrative, we instead reflect on the current state using various methods and with various goals (possibly over multiple LLM calls) with the effect of creating and changing KB objects instead. This can be done directly by the user, with LLM assistance, or by the AI autonomously (depending on the task). Planning can occur in a separate narrative tree for pre-adventure setup, or within a narrative tree (and thus aware of the place in the story) to remember changes, add plans, etc. In-narrative planning may also some details or generate an operator call ("in the morning, you were awakened by...").
  - **Play**: The AI does not update KB objects during normal play, it's too specific of a task. The user can always change objects directly, but it's not something the LLM tries to do, it just focuses on executing. We do what to have triggers and mechanics to switch to planning, however. When we do play, the player may be controlling multiple characters; they need to specify who is acting as if there were multiple people talking at the table. They can 100% just say "Elara wants to..." but it may be more fun for them to pick a character and talk first person: it's where the "Role" part of roleplay comes out. This is orthogonal to operators, so it needs to be supported by Lens, but it's also quite simple because all it does is adds a character marker to the request. 

## RPG Objects Design

We need to design two kinds of objects:  
  1. **Reference Data**: rules and mechanisms that turn free-form writing into playing an RPG
  2. **TYpes and Templates**: predictable shape of stored that can be leveraged by operators 

### Reference Data

#### Rules

We want the core set for playing D&D or doing planning tasks, then try to split them by situation type. Operators pin the base plus any additional rules they need. We do NOT need all the rules of D&D in our rules corpus, because the AI _does not play the entire game_ (it's not an game engine). In particular all the rules for creating player characters don't belong here. So to create a ruleset we will proceed in progressive steps, keeping the artifact for each version in case we need to change our approach later. 

We create two core rule objects:  
  - `rules.engagement`: our AI-player contract (ruleset-agnostic)
  - `rules.dnd`: D&D 2024 rules; like a compressed SRD without stuff we don't need (character creation, reference tables, etc) in the form of a prompt.

#### Reference Objects

Reference materials are different than rules proper because they are **lists of items only relevant if in play**, and even if in play, they may not be that relevant in narrative. In other words, the AI doesn't need to know about a monster until it's in play, or about a spell until a monster can decide to cast it, or the player casts it.  
  - We may be tempted to, for example, include the spells or abilities known to a character their object, but this will just tempt the AI to make the character _do those things_, because we gave it the option. For NPC we DO want the AI to know and select from the stat block's abilities, so it's best to just tell the AI to use what it sees, and keep those details out when we want the player to activate them. So if a player wants to cast a spell they can just do so, resolve things like attacks or saves, report narratively what happened, and move on; however if we want the AI to _really_ talk about the spell, or there are interesting consequences, or the spell is for gathering information the AI knows (like Detect Magic), we need to tell the AI about it. In these cases the player will `@` the spell ("Alice casts @spell.detect-magic, what does she see?") and the AI will get the full details, can show the character casting it, and can describe the results. 

To develop these objects, we just need to extract the text from the rulebooks and format them consistently. Editing may be light or not be needed; some linking may needed. We'll track the following object types:  

  - `spell` one object per spell, full details. We don't really need "indexing" by level, school, etc. as the AI doesn't need to find them.
  - `stat` blocks (monsters, but won't want to bias the AI); mostly full details but we need to format the stat block consistently, and some details and tables may not be necessary. As an extra complication, planning needs to find monsters for encounters, so some indexing by tag will be necessary. This is quite easy to do with pattern matching. We'll want to extract `cr:` and `habitat:` to start with.
  - `item` will cover magic items, and `equipment` more normal items you can find often or in stores. These are not necessary unless the AI can find them and put them in the world as loot or store inventory for the players, and this is not very easy to do! We can use type/tags, rarity/GP cost and create a custom prompt to search for them, much like we do for stat blocks. 

#### Using tags

So, you cast `@spell.fly` and you fly, but later the AI forgets you are flying or who is flying and not flying (maybe it's a different scene and this fact may literally be lost in the summaries), so now you have to rollback and add to your prompt that "remember I was are flying" and the AI doesn't even see your past prompts, so this may become endemic and not fun. We don't want to manage state nor micro-manage editing objects all the time for that, but what if we used tags for "micro-state", things like conditions or roughly single-word mechanical rules applied to a character? This like putting condition rings on your mini, and would be mostly on the user to track (when things actually do apply and get removed is quite complicated... we have counter-spells, saving throws, concentration checks, durations...) but even then saying `kb tag pc.alice -a speed:flying -a concentrating` is not super-hard, and because these are all rules, the words are limited and easy to auto-complete in a UI. Now the AI and the user can both know you are flying and concentrating (tricky to remember at the table!). 
   - Note that we definitely will NOT have instances of objects for all the stuff we encounter! Recurring NPCs sure, but definitely not the hundreds of monsters players will slay over time, and certainly we have no interest in tracking conditions on them: that has to be done fully by the player, and they can just say "goblin 3 is restrained" and now the local narrative says that... but it's very temporary. The tags are more useful out of combat for narrative purpose, it's absolutely not necessary to say we're concentrating every time to cast Guidance etc. Again, Lens is NOT a simulation, it's a structured narrative aid.

### About Campaign State

Tracking state in object feels attractive, but it's often a trap. By definition, what is happening in the story is what the narrative tree is supposed to track, so that "state" in object mostly how it affects named instances of things we track, which are essentially locations, people, and groups of people (`faction`s). The main object we need for grouping narrative cohesion (quests can be unruly things) and track what hasn't happened yet or in-motion is a `front`. 

So, in summary, what do we need?
  1. We track the things and people we care about, and some of them have secrets and plans to discover. These can be created and refreshed occasionally via design operators.
  2. We will still want a general object pinned to our narrative root that captures tone, genre, setting frame, etc. By definition this is _not_ state, because it does not change! It doesn't have mechanical bearing, something like `lore.setting` would work.
  3. We use a `front` for everything else. The `advance` operator (the mechanism to update fronts), also keeps separate state to roughly track the passage of time.

## RPG Object Templates

This section contains the RPG Object templates, and their rationale. You can import these directly by running `lens kb extract` on this document from the dataset or folder you want to update. 

### Player Characters (`pc.*`)

One object per PC. We should have a template and guidance, but it's the job of the user to fill this in, since it's their avatar and they have their character sheet.

Content per object is just enough to get the AI to talk about the character and talk _as_ the character (represent them). It is tempting to add their powers, ideals, fears, etc. but we need to optimize these objects for play, NOT planning. Adding details is a double-edge sword because the AI may take too much initiative with powers, or use this information at inopportune times, like "you said this character has green eyes, so let me mention their green eyes EVERY TIME they are mentioned". So we need to strike a balance of enough details that they not just "she squinted her green eyes as she notched her arrow," but also not get "Alice thought about her trouble childhood at the orphanage as she notched her arrow." Going for something like "Alice deftly jumped the narrow wall to get a good angle as she notched her arrow" (she's dextrous and needs to trigger sneak attack, you see?)

```kb
---
id: pc._template
---
<!-- Player Character. Usage: most details owned by player; use these objects to correctly describe and speak as these character when the player makes them act. -->
Name (plus any nicknames or code-names we'd see them called)

- Appearance: (species, presented gender, physique, distinguishing details, visible kit, mannerisms, how they talk, etc.)
- Context: (relevant background, goals, motivations, personal struggles - nothing too detailed; enough to flavor their interactions, but the player is expected to control when these are surfaced)
- Affiliations and Relationships: (only non-obvious and story-relevant) 
- How they solve problems: (key strengths and weaknesses, passive features that make a difference in how the character interfaces with the world that matter to the DM, like high passive perception, darkvision, movement speeds, etc. Do not include specific active skills or powers: it is the player's responsibility to surface when these are revealed and used.)

<!-- TAG POLICY: ALWAYS tag a `pc` object with its total character level, e.g. `level:3` to balance encounters; optionally add user can add mechanical rule tags, like conditions. Also link them to any faction of which they are members. -->
```

### Location (`loc.*`)

Geography is important and fractal, we'll need to know the region we're in and sometimes the city, or even the tavern or someone's room, if for some reason that matters.
Critically, We only want to create objects for places that _matter_, so somewhere we're at for a while, or somewhere we're returning to. In a social game, maybe every room in a mansion has a record, in other adventures just the overland we travel, and then a bunch of places we visit and remember only in narrative summaries, if at all.

If want to store places so we can return to them, we will need to find them again later! Therefore, we need a map. A map is just a tree, so all we need to do is link locations, expand the graph, and we have a "map". If we care, we can note distances or containment, but since these are LLM-processed, we can use the objects text for that, adding as needed (the "only what is mentioned or planned for exists" rule). So each location should link to its parent location, and we can use a recursive tag traversal of the root location to make a map (e.g. `lens kb with-tag loc.kingdom --recurse --expand --same-type` to get all the locations in the kingdom).  

```kb
---
id: loc._template
---
<!-- Any type of Location. Usage: Ensures continuity when revisiting places; we ALWAYS link a location to the one of which it's part (or lore.work for roots), which lets us create a map graph of our setting. -->
Name

- Type of location (everything else below is optional, just add if relevant to story)
- Scale and distance to other places
- Sensory feel: looks, sounds, smells
- Social feel: who is usually here, mood
- History/usage: how this place has been used over time
- Why it matters: dangers, opportunities, adventure relevance
- Tensions or secrets

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag a `loc` object with the loc.id that contains it, if any. -->
```

### NPC's (`npc.*`)

NPCs may have less flavor than a PC, but the AI can have a full view on their motivations, goals,  abilities, and secrets, as they are fully controlled by the DM. They may be connected to a stat block, and we can even seed a secret (would be decoded when the AI sees it).

```kb
---
id: npc._template
---
<!-- Non-player Character. Usage: A developed, recurring character controlled by the AI. NOT needed for transient characters such as one-off vendors and monsters. -->
Name (plus any nicknames or code-names we'd see them called)

- Appearance: (species, presented gender, physique, distinguishing details, visible kit, mannerisms, how they talk, etc.)
- Affiliations and Relationships: (particularly towards PC's;) 
- How they solve problems: (key strengths and weaknesses, go-to abilities they would use, when, and how they present)
- Goals and Motivations: (what they want, as far as people know)
- Statues and Moves: (what they are up to, as far as people know)

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag an `npc` object with mechanical rule tags, like movement speeds and resistances;  link them to their `stat` block, factions, or a front they own, if any. -->
```

### Faction (`faction.*`)

Factions mostly provide a mechanism to give NPC's or monsters we don't track individually a place in the world, some flavor and some motivation. So in an encounter you could say you are in a location (specific to the encounter, or sometimes in KB), fighting one or more `factions`, and then the `stat` blocks for the encounter could be attached to each faction (or we can just say it's rogues or zombies), so the AI can model behavior in a good narrative way for one or multiple groups.

```kb
---
id: faction._template
---
<!-- Faction or Group. Usage: Defines intent and behavior for groups of NPCs; useful for contextualizing fronts and npc/monster behavior. -->
Name (plus any nicknames or code-names we'd see them called)

- Who they are and what they believe or want
- How they operate (methods, subtlety or brutality)
- Where they are strongest, who their recruit (particularly the hard rules)
- How they feel about the party and other factions
- Ongoing plans or operations

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag a `faction` object minimally (they are linked to); you can include the loc headquarter or the pc/npc leader  -->
```

### Front (`front.*`)

Fronts let use steer the story forward and provides the hooks and challenges for the players. They are the quests to solve, the rituals to stop, and the horrible "coincidences" that are about to unfold. They are usually pinned to narrative when relevant, so they should be compact.

```kb
---
id: front._template
---
<!-- A Front is a changing situation of some kind we want to track. Usage: track cross-cutting problems, clocks, changing situations; updated by the "advance" operator. -->
Name (any way we'd be referencing this problem)

- Problem: one or two sentences
- Stakes if ignored
- Known to PCs: what the party believes
- Phases or beats: how it might escalate, where it's at
- Possible resolutions

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag a `front` object minimally (they are either pinned or spawn changes and narrative during planning); you can include a loc key location or the driving faction or npc  -->
```

### Lore (`lore.*`)

Lore is our catch-all container for tracking specific bits of knowledge that don't fit anywhere else. For example `lore.world` can be our setting, or we could have lore about important items (McGuffins that need to work in a specific way). Lore regarding other objects can also live here: so a `pc.alice` can also have a `lore.alice` (NOT linked from the PC object) that contains details used in planning specific trials for her, but not relevant to know during play. We could prepare lore objects for specific exposition (e.g. wording for a book or instructions for a puzzle) and pin/tag them just when needed in the narrative later.

```kb
---
id: lore._template
---
<!-- Arbitrary details about anything. Usage: Often used in planning so details are not surfaced to narrative all the time; mention or pin this directly when needed. -->
Gathered knowledge about any other object or topic

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag a `lore` object to point to the object it is about (if any), and not the other way around (it's a separate object to keep it isolated/secret)  -->
```

## RPG Operators

As we discussed above, we want to cleanly separate "Planning VS Play", so each RPG operator lives in one or other.

| Operator | Mode | Purpose | Trigger |
|---|---|---|---|
| `design` | Plan | Create/update KB objects | As needed |
| `play` | Play | Prose + roll requests | Default |
| `converse` | Play | Better conversation via prompts | Player wants dialog |
| `encounter` | Plan | Aid player in running combat | Rolled initiative |
| `advance` | Plan | Updates `front` objects as time passes | Player explicitly passes time |

### Create and Refine Knowledge For Your Game with `design` 

A dedicated narrative sub-tree where the conversation is not story, it's collaborative design workspace, with KB objects changes are the product. We can start from a dedicate narrative tree, or create a self-closing tag anywhere in the narrative so we have the story so far. Sub-sections may open for dedicated sub-tasks with specialized prompts.

The model emits certainly emits discursive text and collects answers from the user, but the replies also include fenced blocks compliant with the `kb extract` command format. This lets the model focus on content rather than prose style, and makes extraction deterministic. Secrets work because they are encoded as they come out of the LLM.

The operator needs to design objects tailored to play use: concise and appropriately linked and tagged. The player should be able to start playing but pinning an expanded object like `loc.owl-rest-tavern+` or `front.goblin-raids+` and the links (plus the baseline rules and pc pins _should_ be sufficient to get things playing).

The operator _does not_ author static high-level objects like `lore.world` that setup the general setting and tone. Those are added by the player, or they can use a normal edit operator for assistance.

Other Considerations:  
  - Ideally we'll want the LLM to perform "scene changes" by using sections with new pins, for example if the tavern is `loc.springfield` by the rules of `loc` there will an edge to it, so when the players leave the tavern the scene can pin Springfield instead.
  - It would be pretty easy to create a `map` operator that uses the `loc` graph to tell the AI what's around, so exploration can lead towards known places. Of course it's ideal to just come up with places as needed by the story, we then just need to decide if they are worth remembering. This goes back to maybe needing non-advance way to remember things.

#### Design objects
The bulk of the knowledge that drives the design flow lives not in the system prompt but in `design` KB objects that can be pinned into the design sub-tree. The root prompt has a knowledge of what they are and what's in them, and then asks the user what they want to do: a session zero phase sequence, create or refine objects like locations and factions, create example adventure hooks, plan encounters, etc. 

The operator then creates sub-sections that have that type of design task pinned in their front matter, and can even chain a write operator from what the user asked to do to get the section content started without repetition. When the user is done, we simply call `kb extract` on that design sub-folder and import all the knowledge created! The user can of course skip the chat and create a design operator already pointed to a specific design object, and get going right away.

The set of design objects will evolve over and refine over time, but they will be things like to deliver:  
  - Location build-out: edit one or more locations, correctly linked  
    - Large geography, cities, or structures to explore, from homes to dungeons
  - Advenute build-out: create or update a front, including related factions and NPCs
  - Encounters design: location (stored or not), type (social, stealth, combat, dynamic), who's there (mobs, factions, NPC's), related fronts
  - Finding and selecting items like a balanced amount of appropriate monsters or proper loot based on some requirements

### Play General Scenes with `play`

The primary operator. Receives directorial intent from the player, authors the scene, maintains the authority model. This is where most time is spent.

**Two modes — not a rigid template**:

*Flow*: Default. The AI narrates freely. The world breathes. NPCs have texture. Scenes develop without requiring stakes at every beat. The AI should hold flow mode for extended stretches — not every paragraph needs pressure, and trying to inject it produces a mechanical, exhausting rhythm.

*Stakes*: When risk is live — something can go wrong, a decision is being forced, a check is warranted. The AI establishes what's at risk, names the check type and DC if needed, and narrates the consequence after the player reports results. The AI never describes outcomes before the roll.

Transitions between modes are fluid, driven by the fiction. The mode is not a piece of data, is a continuum to balance. 

**The authority model in practice**:
- Player input is character intent; the AI authors the attempt and the world's response
- World assertions by the player are treated as character impressions, not confirmed facts, until validated through play
- NPC behavior declared by the player is treated as hoped-for outcome; the AI decides what the NPC actually does
- Declared success is treated as goal, not result; the AI decides if it works or calls for a check
- The AI holds these limits while staying cooperative — the resistance is the world working correctly, not the AI working against the player

**System prompt idea**: Critical to get right. Posture + authority model + flow/stakes mode description + when to suggest `converse` (long dialogue developing) and `encounter` (initiative is called for). Knows the to call for a `design` session.

## Chat with NPC's (or among PC's) with `converse`

An explicit "we're in conversation" mode. Long conversations are not information-dense but they are often the best parts of a session — relationship-building, deception, revelation under pressure, negotiation. They need room to breathe without the AI feeling compelled to move the plot forward. `play` has authorial impetus to advance the scene; `converse` has explicit direction to resist that impetus.

Not targeted at a single NPC. The mode covers any conversational scene — one NPC, several, a group council, an interrogation with two suspects in the room. Making it character-specific would be brittle; making it "we're in conversation" gives the player a clear lever they control directly.

**How it works**: Sub-node. The player directs conversational goals ("Elara probes him about the shipment without revealing what she knows"). The AI voices all participants, including the PC's side if the player's direction is high-level. When the node closes, it summarizes as what changed — relationships shifted, information revealed, commitments made — not as a transcript. Consequences that need to land in the fiction go to `play` or `advance` after.

**System prompt idea**: "You are in a conversation. Voice all participants with their own goals, limits, and things they won't say. The player directs what their character is trying to accomplish. Do not advance the plot or resolve the scene — let the conversation develop. On close, summarize: what changed in relationships, what was revealed, what was decided."

**Trigger**: Player invokes directly when a conversation warrants it, or `play` suggests it when a dialogue is clearly developing depth.

## Roll initiative! It's an `encounter`

A focused sub-node for structured combat. Applies exactly while initiative is being tracked; exits when initiative ends.

**Trigger**: Operator, can be called by the player or DM when initiative is rolled. However, the AI needs to have sufficient mechanical content to offer a meaningful encounter. Calling the `design` operator for this task may be required before the encounter can start if it was not planned.

**Setup phase**: The AI describes the encounter — location, what the enemies are trying to accomplish (not fine-grained or "attack," but tactics, and why they're here and what they want... could be just hungry zombies too), and what tactical features of the environment matter. Encounter weight is established narratively here: skirmish, grind, or something to potentially flee from.

**Running phase**: Player describes character actions and reports outcomes. The player actually controls everyone, but the AI is charged to state enemy intent as a director before they act (e.g. "the wounded one falls back, the captain tries to cut off the exit"). The AI will know the skills, powers, and strengths of enemies via stat blocks, and will need to use those facts: casters evade and fire, pack hunters swarm, flyers swoop, etc. Enemies are also characters with goals: a bandit losing may break and run, while the leader may pivot to a hostage gambit when cornered; cultists will sacrifice themselves to complete the ritual; and so on. Player-reported outcomes ("the flanking guard is down, the captain is bloodied") drive the AI's next beat.

**Why not `play`**: Context economy. Combat needs enemy KB objects, terrain, and tactical state — not the full campaign graph. The sub-node architecture enforces this focus naturally.

**System prompt idea**: Something like "Direct enemy tactical intent as a narrator. The player handles all mechanics. Respond to player-reported outcomes. Enemies are characters with goals — let them react, adapt, and make decisions under pressure." but probably more complex so that the AI is smart and respects boundaries.

Sub-node closes with a specialized summary that surfaces to the parent section, focusing on outcome and the state of survivors.

## Pass The Time with `advance` 

The world takes its turn the player skips time. This is a lot of like `design`, but specifically designed to update `front` objects in targeted ways; it will also pick up at least one level of objects linked to each front, for context.

**Trigger**: The player explicitly invokes when time passes — rest, travel, downtime. "We rest overnight." "We spend three days at the inn." "We ride to the capital." This hands the initiative to the world. What happens during that time is the AI's call: a rest might be interrupted; a journey might have a consequence; downtime might find something changed while the party wasn't watching. 

### Guidelines

- **Fronts as drama, not simulation**: A front KB object establishes an expectation — a threat in motion, a clock running, a plan unfolding. `advance` makes that expectation feel real. Two patterns:
- *Story beats*: A front describes what a faction or NPC is working toward in prose. `advance` reads the current state and decides what they've done during the elapsed time, improvising plausibly from what's established. No rules system required — only the established expectation and the elapsed time.
- *Clocks and Timers*: A front KB object may carry a note like `Days remaining: 8` or `Number of council members convinced by the enemy: 3 out of 7 (every day there's a 10% chance another one turns)`. `advance` instructs the AI to notice such elements and increment/decrement timers and clocks in a way that makes sense. Each of these carries a consequence.
- **Only plan what's been established**. Everything else the AI improvises as if it had been planned all along. Fronts are dramatic expectations, not state machines. The goal is that consequences feel earned, not that anything was actually simulated. This is why we only update fronts... they are the kind of objects that advance.

### Mechanics

**How much do we advance?**: The operator needs to maintain its own object, `state.advance`, with a log of every time it was called. Each entry contains:  
 - The narrative address where it was called
 - How long it estimates has passed since the last "advance" call (or the beginning of the narrative). To do this it has to crawl backwards from the current narrative address to the previous one, collect text and summaries, and... just make its best guess. Players are supposed to advance as they rest daily, so this should not be too hard.
 - How long the operator itself is adding to the clock. This is at most what was asked for by the player (like sleeping overnight) but could be less (one the third day of a week-long trip, something happens and advance stops there; the player will have to advance again to complete the trip once that's resolved). This lets the operator "catch up" as much as necessary regardless how often it's called.

**How does it run**:
1. Loads fronts+ and its own state
2. Performs a crawl to the previous `advance` and collects narrative
3. Generates a "luck roll", a random number from 1 to 100 for every front and for the current "rest period"; these are passed as metadata to the AI, which can use them to determine how some clocks advance, or reference encounter tables!
4. Calls the AI with all the above with a prompt to:
  - Estimates time passed since the last advance by looking at the narrative crawl result
  - Decides if the requested rest period will be completed in full or not; this is the MAX time that will pass
  - Reviews all active fronts and decides what happens in each
  - Decides whether some event in a front actually interrupts the advance (war broke out, stop hanging out at the inn!) and finalized time that passed
  - Generates `kb extract` style blocks to edit fronts
  - Generates a line to append to the state log (Lens will only look at the last line anyway) 
  - Closes and returns to parent, generating a summary of anything the players would have heard about
  - Emits a follow-up operator to determines how to continue the story: PC's wake up, a messenger arrives, wolfs attack the camp, etc.
