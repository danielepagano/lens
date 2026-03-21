# Lens RPG Support - Design

## Core Philosophy

Lens is about making Narrative Simulations; it's overkill for writing short stories and it's too linear for a sprawling novel. What it's good at is directing AI with curated instructions and context, keeping it focused on the now while funneling the exact details it needs to function; in other words, it's good at using AI for responsive collaborative storytelling, the AI taking a role and surprising you. It's not about the written results, it's about the experience you have while using it. In other words, Lens aims to make playing a real RPG with an AI possible.  

With that said, aiming for "just as good as the table" or "just as polished as a videogame" would be unwise: token prediction models have intrinsic limitations, so we need to keep our goal more narrow and more specific. What Lens aims to provide is **the experience of playing an arbitrary RPG character in an open-ended textual videogame**. What does that mean?  

- The player can bring their own character or party from any system and setting. However, the player has to understand the system and setting, and be willing to put in the work to play through the system and the rules. If the player wants automation and spectacles there are videogames, but if they are itching to sit down with a character sheet and see what this character would do and how they'll fare, without a game table, they should find it here. 
-  The player is neither "trying to win" nor "being the player and letting the GM do everything else". This is a collaborative endeavor, and the AI is there to give you interesting challenges, but not to do all the work. The AI will do better when you put more work into helping it, but Lens tries to minimize, organize, and force-multiply the player's effort vs using a chat with a prompt and maybe a RAG.
- The AI is not trying to be the "full DM", it's a narrative DM that does the writing, but the player is still doing rolls and a lot of mechanical work. On the other hand, the AI "does all the talking" so it writes what the player characters say and do, but while giving the player agency to decide what that is.

Let's look at some GM tasks, and how Lens with AI handles them:  
- **Understand what the players are trying to do, and which rules apply, then make mechanical decisions about what the players are trying to do**: we always need this, but we can compartmentalize some of this knowledge as we don't need combat rules out of combat, etc.
- **Control non-player characters and have them follow (mostly) the same rules**: we need to specifically classify player characters as such and pin them to the session at all times; NPCs would be different objects and the AI is free to control them, as they are differently annotated. Very specific operators could simulate an NPC generating dialog, reinforcing their voice, and even limiting or distorting the information available to that NPC, running them in "their own AI sandbox" so to speak.
- **Bring the world to life in an actionable way to players through words, and have it react appropriately**: the pinning system surfaces the right details for the current scene. An encounter object carries the specific interaction hooks — the same bridge can be a peaceful crossing or an ambush depending on what's prepared. `play` reads the encounter and adapts.
- **Enforce the world's continuity**: When something interesting happens, we have mechanisms to remember it in the KB; maybe a location changed, or an NPC has something new to remember. This is on top of fractal summarization, which keeps more relevant details closer and keeps the context size small for the far past.
- **Let players have agency while also letting the story move forward**: the player drives all action through `play`; preparation through encounter objects and fronts ensures the world has momentum and surprises. The `advance` operator moves fronts forward when time passes, creating pressure and consequences without the player having to manage it.
- **Put the players in interesting and difficult situations so they can use their skills and guile to succeed**: this is the job of `design` — building encounter objects that are fun, fair, and have secrets. The encounter object is the DM's prep; `play` is the DM's execution. Secrets can be encoded so even the player running `design` doesn't see them until play reveals them.

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

The key design impetus of Lens is to curate and constrain the knowledge set and instructions given to the AI, so it can behave predictably without bloating the context window. Hierarchical summarization makes this already possible with just a bit of user discipline with sections, but when running a game we may have both a large ruleset (baseline knowledge corpus) and demand more from the AI in terms of prompt compliance. We therefore need all the tricks we can to keep context and prompts small and focused.

To this extent, we divide our experience in two alternating phases:  
  - **Planning**: during planning we don't directly generate narrative, we instead reflect on the current state using various methods and with various goals (possibly over multiple LLM calls) with the effect of creating and changing KB objects instead. This can be done directly by the user, with LLM assistance, or by the AI autonomously (depending on the task). Planning can occur in a separate narrative tree for pre-adventure setup, or within a narrative tree (and thus aware of the place in the story) to remember changes, add plans, etc. In-narrative planning may also add details or generate an operator call ("in the morning, you were awakened by...").
  - **Play**: The AI does not update KB objects during normal play, it's too specific of a task. The user can always change objects directly, but it's not something the LLM tries to do, it just focuses on executing. We want triggers and mechanics to switch to planning, however. When we do play, the player may be controlling multiple characters; they need to specify who is acting as if there were multiple people talking at the table. They can 100% just say "Elara wants to..." but it may be more fun for them to pick a character and talk first person: it's where the "Role" part of roleplay comes out. This is orthogonal to operators, so it needs to be supported by Lens, but it's also quite simple because all it does is add a character marker to the request. 

## RPG Objects Design

We need to design two kinds of objects:  
  1. **Reference Data**: rules and mechanisms that turn free-form writing into playing an RPG
  2. **Types and Templates**: predictable shape of stored data that can be leveraged by operators

We also have three **layers** of objects:  
  1. The **core** rpg layer: the minimum required that powers our RPG system and operators
  2. The **game system** layer: rules and data specific to a game system, e.g. D&D, Cypher System, etc.
  3. The **setting** layer: lore and other reference data for a specific setting in the system, e.g. Grim Hollow, Numenera, etc.

Each layer is (at least) one Lens `dataset`.

### Reference Data

#### Rules

Operators pin the core rules plus any system-specific rules they need. We do NOT need all the rules of a game in our rules corpus, because the AI _does not always play the entire game_ (it's not a game engine). In particular all the rules for creating player characters don't usually belong here (they are _at most_ design modules). 

We create two core rule objects:  
  - `rules.rpg`: our AI-player contract; core layer, ruleset-agnostic
  - `rules.system`: system-specific rules. Lens ships with "Lens in the Dark", a simple "Forged in the Dark" ruleset (https://bladesinthedark.com/licensing) tuned for AI use, but it can be overridden by a game system ruleset by simply replacing that object id in a higher-priority dataset.
    - `rules.*`: some systems benefit from having multiple rulesets for different phases of play (e.g. Blades in the Dark's downtime, D&D's Bastions, etc., very specific combat rules like in some Powered by the Apocalypse games). In these cases the system rules can just be the foundation, and then the player can alternate phases by splitign the rules and pinning as needed. This is the parallel to `design` having different modules for different things you can work on.

#### Reference Objects

Reference materials are different than rules proper because they are **lists of items only relevant if in play**, and even if in play, they may not be that relevant in narrative. In other words, the AI doesn't need to know about a creature stat block until it's in play, or about a special ability until something in scene can use it or the player invokes it.  
  - We may be tempted to, for example, include every ability known to a character on their object, but this will just tempt the AI to make the character _do those things_, because we gave it the option. For NPCs we DO want the AI to know and select from the stat block's abilities, so it's best to just tell the AI to use what it sees, and keep those details out when we want the player to activate them. So if a player uses an ability they can resolve attacks, saves, or other checks at the table, report narratively what happened, and move on; however if we want the AI to _really_ engage with that ability, or there are interesting consequences, or it reveals information only the AI should adjudicate, we need to put the reference in context. In those cases the player can `@` the relevant KB object (e.g. in a fantasy rules corpus: "Alice casts @spell.detect-magic, what does she see?") and the AI gets the full details, can show the character using it, and can describe the results. 

To develop these objects, we just need to extract the text from the rulebooks and format them consistently. These are not really used by operators, but they are useful prompt context. For example in D&D we can track object types like:  

  - `spell` one object per spell, full details. We don't really need "indexing" by level, school, etc. as the AI doesn't need to find them.
  - `stat` blocks (monsters and similar, but we won't want to bias the AI); mostly full details but we need to format the stat block consistently, and some details and tables may not be necessary. As an extra complication, planning needs to find creatures for encounters, so some indexing by tag will be necessary. This is quite easy to do with pattern matching. For games that use them, fields like challenge rating and habitat are good candidates for tags.
  - `item` will cover magic items, and `equipment` more normal items you can find often or in stores. These are not necessary unless the AI can find them and put them in the world as loot or store inventory for the players, and this is not very easy to do! We can use type/tags, rarity/GP cost and create a custom prompt to search for them, much like we do for stat blocks. 

#### Using tags

So, you cast `@spell.fly` and you fly, but later the AI forgets you are flying or who is flying and not flying (maybe it's a different scene and this fact may literally be lost in the summaries), so now you have to rollback and add to your prompt that "remember I was are flying" and the AI doesn't even see your past prompts, so this may become endemic and not fun. We don't want to manage state nor micro-manage editing objects all the time for that, but what if we used tags for "micro-state", things like conditions or roughly single-word mechanical rules applied to a character? This like putting condition rings on your mini, and would be mostly on the user to track (when things actually do apply and get removed is quite complicated... we have counter-spells, saving throws, concentration checks, durations...) but even then saying `kb tag pc.alice -a speed:flying -a concentrating` is not super-hard, and because these are all rules, the words are limited and easy to auto-complete in a UI. Now the AI and the user can both know you are flying and concentrating (tricky to remember at the table!). 
   - Note that we definitely will NOT have instances of objects for all the stuff we encounter! Recurring NPCs sure, but definitely not the hundreds of monsters players will slay over time, and certainly we have no interest in tracking conditions on them: that has to be done fully by the player, and they can just say "goblin 3 is restrained" and now the local narrative says that... but it's very temporary. The tags are more useful out of combat for narrative purpose, it's absolutely not necessary to say we're concentrating every time to cast Guidance etc. Again, Lens is NOT a simulation, it's a structured narrative aid.

### About Campaign State

Tracking state in objects feels attractive, but it's often a trap. By definition, what is happening in the story is what the narrative tree is supposed to track, so "state" in objects is mostly how it affects named instances of things we track, which are essentially locations, people, and groups of people (`faction`s). The main object we need for grouping narrative cohesion (quests can be unruly things) and track what hasn't happened yet or in-motion is a `front`. 

So, in summary, what do we need?
  1. We track the things and people we care about, and some of them have secrets and plans to discover. These can be created and refreshed occasionally via design operators.
  2. We will still want a general object pinned to our narrative root that captures tone, genre, setting frame, etc. By definition this is _not_ state, because it does not change! It doesn't have mechanical bearing, so something like `lore.world` would work.
  3. We use a `front` for everything else. The `advance` operator (the mechanism to update fronts); to use it, we need to **roughly track the passage of time**.

#### The passage of time

We only care about the passage of time in two situations:  
  1. It has a mechanical implication in the game rules, like for rests. Because we are not the game engine, the player is supposed to track time for things like expiring abilities or resources, but the AI needs to know roughly the passage of the day for narrative purposes. This should happen organically as the story happens, at most we need to point out in the prompt that this matters.
  2. It advances the story outside of what is happening in the narrative. This is optional: a simple story can have nothing of relevance happening in this way, and even if it does, the AI can just improvise what would have happened on the spot. In some cases where we actually want to tell a story with real pressure, we DO need to track time so the AI can setup and then satisfy expectations. A key fact is that narrative need not be linear storytelling, it can jump back and forth (flashbacks could be a game mechanic!) or the player may want to create multiple parallel narrative trees (split or yet unmet party, or a Westmarch-style campaign); in these cases, the information we accumulate over time in KB may not be accumulative in a simple way. This is a key reason why progress is isolated to `front` objects: they are the only ones that really care about time.

So, how do we track time if we want to do in an advanced way? We follow these rules:  
  1. Each narrative needs to belong to a "timeline", which we can pin to it, e.g. `timeline.alice-prologue`. This object just contains two lines: a starting reference (could be a date or just an arbitrary description; it's for the player only), and the current day number after that day: the **day counter**. The user advances the timeline by using the `advance` operator to increment the day counter by 1 or more, and evaluating what happens.  
    - The day counter moves forward every day at the same time; in a modern setting it could be midnight, in a fantasy one it could be a dawn. It doesn't have to be perfect as long as it's self-adjusting. 
  2. Each `front` belongs to (that is, is tagged with) one timeline, and is advanced when that timeline advances using the `advance` operator (described later). 
    - A front cannot belong to multiple timelines because it needs to advance with it (it's a state, not a log), and also the point is that the narrative and the front are tied. If a user wants to track a rising threat across multiple timelines played one after another, really only the first one could have affected the front, because time has already passed! In reality for these situations a front would be created only once timelines converge or a timeline "runs into" the front and can deal with it. Causality is a thing.
    - To run time-overlapping narratives, the user can simply create multiple timelines with the same start reference time, and start them at different day numbers, advancing them whenever they play that narrative.

## RPG Object Templates

This section contains the RPG Object templates, and their rationale.

### Player Characters (`pc.*`)

One object per PC. We should have a template and guidance, but it's the job of the user to fill this in, since it's their avatar and they have their character sheet.

Content per object is just enough to get the AI to talk about the character and talk _as_ the character (represent them). It is tempting to add their powers, ideals, fears, etc. but we need to optimize these objects for play, NOT planning. Adding details is a double-edged sword because the AI may take too much initiative with powers, or use this information at inopportune times, like "you said this character has green eyes, so let me mention their green eyes EVERY TIME they are mentioned". So we need to strike a balance of enough details that they're not just "she squinted her green eyes as she notched her arrow," but also not get "Alice thought about her troubled childhood at the orphanage as she notched her arrow." Going for something like "Alice deftly jumped the narrow wall to get a good angle as she notched her arrow" (she's agile and needs to trigger sneak attack, you see?)

```kb
---
id: pc._template
---
<!-- Player Character. Usage: most details owned by player; use these objects to correctly describe and speak as these characters when the player makes them act. -->
Name (plus any nicknames or code-names we'd see them called)

- Appearance: (species, presented gender, physique, distinguishing details, visible kit, mannerisms, how they talk, etc.)
- Context: (relevant background, goals, motivations, personal struggles - nothing too detailed; enough to flavor their interactions, but the player is expected to control when these are surfaced)
- Affiliations and Relationships: (only non-obvious and story-relevant) 
- How they solve problems: (key strengths and weaknesses, passive features that make a difference in how the character interfaces with the world that matter to the GM, like sense, movement speeds, etc. Do not include specific active skills or powers: it is the player's responsibility to surface when these are revealed and used.)

<!-- TAG POLICY: Link PCs to any faction of which they are members. -->
```

### Location (`loc.*`)

Geography is important and fractal, we'll need to know the region we're in and sometimes the city, or even the tavern or someone's room, if for some reason that matters.
Critically, we only want to create objects for places that _matter_, so somewhere we're at for a while, or somewhere we're returning to. In a social game, maybe every room in a mansion has a record, in other adventures just the overland we travel, and then a bunch of places we visit and remember only in narrative summaries, if at all.

If we want to store places so we can return to them, we will need to find them again later! Therefore, we need a map. A map is just a tree, so all we need to do is link locations, expand the graph, and we have a "map". If we care, we can note distances or containment, but since these are LLM-processed, we can use the objects text for that, adding as needed (the "only what is mentioned or planned for exists" rule). So each location should link to its parent location, and we can use a recursive tag traversal of the root location to make a map (e.g. `lens kb with-tag loc.kingdom --recurse --expand --same-type` to get all the locations in the kingdom).  

```kb
---
id: loc._template
---
<!-- Any type of Location. Usage: Ensures continuity when revisiting places; we ALWAYS link a location to the one of which it's part (or lore.world for roots), which lets us create a map graph of our setting. -->
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

### NPCs (`npc.*`)

NPCs may have less flavor than a PC, but the AI can have a full view on their motivations, goals, abilities, and secrets, as they are fully controlled by the GM. They may be connected to a stat block, and we can even seed a secret (would be decoded when the AI sees it).

```kb
---
id: npc._template
---
<!-- Non-player Character. Usage: A developed, recurring character controlled by the AI. NOT needed for transient characters such as one-off vendors and monsters. -->
Name (plus any nicknames or code-names we'd see them called)

- Appearance: (species, presented gender, physique, distinguishing details, visible kit, mannerisms, how they talk, etc.)
- Affiliations and Relationships: (particularly towards PCs)
- How they solve problems: (key strengths and weaknesses, go-to abilities they would use, when, and how they present)
- Goals and Motivations: (what they want, as far as people know)
- Status and Moves: (what they are up to, as far as people know)

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: you may link a base NPC object to mechanical details like a `stat` block, a lore object, their faction, or a front they own, if any. -->
```

### Faction (`faction.*`)

Factions mostly provide a mechanism to give NPCs or monsters we don't track individually a place in the world, some flavor and some motivation. So in an encounter you could say you are in a location (specific to the encounter, or sometimes in KB), fighting one or more `factions`, and then the `stat` blocks for the encounter could be attached to each faction (or we can just say it's rogues or zombies), so the AI can model behavior in a good narrative way for one or multiple groups.

```kb
---
id: faction._template
---
<!-- Faction or Group. Usage: Defines intent and behavior for groups of NPCs; useful for contextualizing fronts and npc/monster behavior. -->
Name (plus any nicknames or code-names we'd see them called)

- Who they are and what they believe or want
- How they operate (methods, subtlety or brutality)
- Where they are strongest, whom they recruit (particularly the hard rules)
- How they feel about the party and other factions
- Ongoing plans or operations

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag a `faction` object minimally (they are linked to); you can include the loc headquarters or the pc/npc leader  -->
```

### Front (`front.*`)

Fronts let us steer the story forward and provide the hooks and challenges for the players. They are the quests to solve, the rituals to stop, and the horrible "coincidences" that are about to unfold. They are usually pinned to narrative when relevant, so they should be compact.

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
  - Timeline anchors: if applicable, specific values of the day counter when something is meant to happen
- Possible resolutions
  - Specific triggers, state of the world, or actions that affect the result
  - Any dependencies on chance, in the form of "every (counter mod x) days there is a y% chance that z could happen"

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag a `front` object minimally (they are either pinned or spawn changes and narrative during planning); you can include a loc key location or the driving faction or npc. Tag it with its timeline if it belongs to one.  -->
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

### Encounter (`encounter.*`)

An encounter is any prepared situation for `play`; not just combat, but also not every situation, it's something worth preparing: a set piece. It acts as DM's script for a scene that has stakes, participants, and rules beyond "the world is there." A friendly but complex conversation with an NPC who has information, but also personality, motives, and conflict; an ambush at a bridge that requires tactical planning; a chase through a burning market with specific mechanics; etc. The encounter carries what `play` needs to run the scene well, and links to the detailed objects (stat blocks, NPC objects, location) that provide depth.

Most encounters are short. If the rules for a situation are simple ("you're talking to a nervous informant who knows X and Y but won't reveal Z"), there is no need to involve the design operator or make an encounter object. If the rules are complex (a multi-phase boss fight with environmental hazards), the encounter says so and may link to a `lore.*` object with more details.

```kb
---
id: encounter._template
---
<!-- A prepared situation for play. Usage: pin this when the scene starts; play reads it as a script. Can be any situation type: combat, social, chase, puzzle, heist, or any mix. Link to participants and relevant objects. -->
Encounter name (short, evocative)

- Situation: (what's happening, in one or two sentences)
- Stakes: (what can go wrong, what's at risk)
- Participants: (who's involved; link npc/faction or stat block objects)
- Scene rules: (special mechanics for this situation — tactical features, environmental effects, conversation goals, chase rules, puzzle mechanics, time pressure. Keep short; link lore object if complex.)
- Triggers: (what causes the situation to shift — dialog escalates, timer expires, reinforcements arrive, secret is revealed)
- Resolution: (how it ends and what should change — front updates, NPC attitude shifts, loot, information revealed)

<!-- ai:secret: Ercynpr guvf grkg jvgu nal vasbezngvba lbh qba'g jnag gur cynlre gb xabj; gur cyngsbez jvyy rapbqr vg gb or bayl NV-ivfvoyr. -->
<!-- TAG POLICY: tag an encounter with the loc where it takes place and any driving front or npc. For combat encounters, tag with difficulty:low/moderate/high. -->
```

## RPG Operators

We cleanly separate "Planning VS Play". The key insight: **play needs exactly one operator because the encounter object IS the operator prompt.** A conversation, a combat, a chase, an interrogation, a puzzle — these are not different operators, they are different _preparations_. The encounter object carries the rules, the stakes, the NPCs, and the situation. `play` reads those objects and adapts. This means:

- No rigid mode switching between "combat operator" and "dialog operator"
- The player can design "you meet NPC X at the bridge" without deciding in advance if it's a friendly chat or a horrible ambush — that's in the encounter object, possibly encoded as a secret
- Situations can mix freely: a conversation can escalate to combat, a chase can pause for negotiation, all within the same `play` flow
- Less spoilery: the player directs `design` to set up a meeting, and the encounter object encodes what actually happens

| Operator | Mode | Purpose | Trigger |
|---|---|---|---|
| `design` | Plan | Create/update KB objects via design modules | As needed |
| `play` | Play | All narrative: prose, dialog, combat, chases, puzzles | Default during play |
| `advance` | Plan | Updates `front` objects as time passes | Player explicitly passes time |

### Create and Refine Knowledge For Your Game with `design`

A design session is a narrative sub-node where the work product is KB objects, not story. Each `lens design` call appends an inline block to the sub-node; the LLM uses `kb_get` and `kb_with_tag` to inspect existing objects and emits fenced `kb` blocks alongside discursive text. When the session is complete, `lens design --end` extracts all `kb` blocks and writes them to the knowledge store in one transaction.

The sub-node is created automatically on the first call, with an ID derived from the prompt and module (e.g. `design-encounter-the-bridge-ambush`). Subsequent calls detect the active session and add blocks rather than creating a new sub-node. This lets the user refine across multiple exchanges before committing.

The operator needs to design objects tailored to play use: concise and appropriately linked and tagged. The player should be able to start playing by pinning an expanded object like `loc.owl-rest-tavern+` or `front.goblin-raids+` and the links (plus the baseline rules and pc pins _should_ be sufficient to get things playing).

The operator _does not_ author static high-level objects like `lore.world` that set up the general setting and tone. Those are added by the player, or they can use a normal edit operator for assistance.

Other Considerations:
  - Ideally we'll want the LLM to perform "scene changes" by using sections with new pins, for example if the tavern is `loc.springfield` by the rules of `loc` there will be an edge to it, so when the players leave the tavern the scene can pin Springfield instead.
  - It would be pretty easy to create a `map` operator that uses the `loc` graph to tell the AI what's around, so exploration can lead towards known places. Of course it's ideal to just come up with places as needed by the story, we then just need to decide if they are worth remembering. This goes back to maybe needing a non-advance way to remember things.

#### Design Modules

Each design module is a `design.*` KB object that contains instructions for the AI on how to approach a specific build-out task — what to ask, what to look up, what to produce. Selecting a module with `--module <key>` pins `design.<key>` into the sub-node's front matter so it appears in every subsequent call's context. Only one module is active at a time; passing `--module` again removes the previous one and pins the new one.

When the user is done with a design session, `lens design --end` runs `kb extract` on the full sub-node and imports all the generated KB objects. Each call to `lens design` adds a new inline block to the sub-node; the user can refine progressively across multiple calls. You can start with no module for an open-ended session, or go straight to a specific task — `lens design "build the ambush" --module encounter` creates a sub-node with `design.encounter` already pinned.

| Module | Defined in | What it produces | Notes |
|---|---|---|---|
| World | `design.world` | `lore.world` + optional deep `lore.*` | Setting and tone — first thing for a new game |
| Player Character | `design.pc` | `pc.<name>` + `lore.<name>` (two objects) | Play surface + planning depth with core questions |
| Front | `design.front` | `front.*` with supporting stubs | Create, groom, develop, retire fronts — arc seeding baked in |
| Encounter | `design.encounter` | `encounter.*` objects | Prepared situations for play (see below) |
| Location | `design.location` | `loc.*` network with parent links | Geography at any scale; story-service gated |
| NPC | `design.npc` | `npc.*` with links and secrets | Recurring characters; story-service gated |

#### Encounter objects: the script for `play`

The central design insight: **an encounter object is not "combat." It's any prepared situation.** A conversation that could go wrong, a negotiation with hidden stakes, a chase through a burning building, a combat with tactical complexity, a puzzle with mechanical rules — or any combination of these in sequence or simultaneously. The encounter object is the _script_ that `play` follows.

This is powerful because:
1. **The encounter carries its own rules.** If combat is complex, the object says so and links the relevant stat blocks. If it's a simple bar chat, the object just describes the principal NPC's goals and what they know. No operator switch needed.
2. **Situations mix naturally.** An encounter that starts as dialog can have a secret trigger for combat. A chase can pause when the quarry turns to negotiate. The object describes the full possibility space; `play` navigates it.
3. **Secrets stay secret.** The player can tell `design` "I'm going to the bridge to meet the informant" and the encounter object can encode that the informant is actually an ambush. The player doesn't see the encounter object contents during design — they see the design conversation. During play, the AI sees the encounter and acts accordingly.
4. **Reuse and adaptation.** An encounter object can be re-used (the patrol at the checkpoint is the same every time) or adapted (the party's reputation has changed, so the guards react differently — update the encounter or let `play` figure it out from the pinned front).

##### The `encounter.*` template

An encounter object is compact and links to everything `play` needs:

- **Situation**: what's happening and why (one or two sentences)
- **Stakes**: what can go wrong, what's at risk
- **Participants**: who's involved, linking to `npc.*`, `faction.*`, or `stat.*` objects
- **Scene rules**: any special mechanics — tactical features, environmental effects, chase rules, conversation goals, puzzle mechanics, time pressure. For most situations this is short. If a situation is mechanically complex (a multi-room dungeon, a heist with phases), the encounter object says so concisely and links to a `lore.*` object with the full rules.
- **Triggers and transitions**: what causes the situation to shift (dialog escalates to combat, the timer runs out, reinforcements arrive)
- **Resolution**: how it ends and what changes

##### How D&D encounters are balanced (combat-specific)

If we're playing D&D, the `design.encounter` module can use the `balance_encounter` tool for combat encounters specifically: the AI discovers stat block candidates via tags (CR, habitat, type), ranks them by narrative fit, then calls `balance_encounter` to produce balanced proposals. But the encounter object it produces is the same template regardless of whether it's combat, social, or hybrid.

The party has an XP budget from PC levels and chosen difficulty (low/moderate/high); allies reduce that budget. Required monsters are fixed; the tool either fills the remaining budget from optional candidates (weighted by narrative-fit rank) or, if required alone exceed the budget, suggests reduced counts. Encounters can be re-balanced on the fly — situations change, allies join, character levels shift — so the encounter object stores the parameters used, and `design` can refresh the balance without rebuilding the whole encounter.

### Play with `play`

**One operator. Fast, flexible, and prepared.**

`play` is the only narrative operator during play. It receives directorial intent from the player, authors the scene, and maintains the authority model. Whether the current beat is exploration, conversation, combat, a chase, or a quiet campfire — it's all `play`. What changes is not the operator, but the **preparation**: the knowledge objects pinned to the current scene.

When an `encounter.*` object is pinned, `play` reads it as a script: it knows the situation, the stakes, the participants, and the rules for this specific scene. When no encounter is pinned, `play` operates in general mode — the world breathes, NPCs react, and the AI follows the baseline rules in `rules.rpg`. The transition is seamless and invisible to the operator machinery.

**Two postures — not a mode switch, a continuum**:

*Flow*: Default. The AI narrates freely. Scenes develop without requiring stakes at every beat. Not every paragraph needs pressure, and trying to inject it produces a mechanical, exhausting rhythm. The AI should hold flow for extended stretches — walking through a market, sharing a meal, arriving at a new place.

*Stakes*: When risk is live — something can go wrong, a decision is being forced, a check is warranted. The AI establishes what's at risk, names the check type and target difficulty if the system uses one, and narrates the consequence after the player reports results. The AI never describes outcomes before the roll.

Transitions between postures are fluid, driven by the fiction. An encounter object may push toward stakes immediately (an ambush) or start in flow (a conversation that could go wrong). The AI reads the room.

**The authority model in practice**:
- Player input is character intent; the AI authors the attempt and the world's response
- World assertions by the player are treated as character impressions, not confirmed facts, until validated through play
- NPC behavior declared by the player is treated as hoped-for outcome; the AI decides what the NPC actually does
- Declared success is treated as goal, not result; the AI decides if it works or calls for a check
- The AI holds these limits while staying cooperative — the resistance is the world working correctly, not the AI working against the player

**What encounter objects change about play behavior**:

When `play` sees a pinned `encounter.*` object, it uses the encounter's scene rules to calibrate:
- In combat-heavy encounters: state enemy intent before they act, track tactical features, respect how many actions each side gets per beat per the pinned rules, direct groups by faction behavior
- In social encounters: voice NPCs with their concealed goals, let conversations breathe, call for checks only when the PC pushes past what the NPC would naturally give
- In chase/escape encounters: track distance narratively, introduce complications, respect fatigue or chase rules from the system
- In mixed encounters: follow the triggers and transitions defined in the object — a negotiation breaks down into combat, a chase ends in a standoff
- In encounters with secrets: the AI knows the secret and plays toward revealing it naturally through the fiction

Without a pinned encounter, `play` defaults to open-world general narration guided by whatever loc, npc, and front objects are pinned.

**System prompt**: The `play` system prompt establishes the GM voice, the authority model, and the gates (ADJUDICATE → NARRATE → RESOLVE → ENGAGE from `rules.rpg`). It does NOT hard-code situation types — it tells the AI to read the pinned encounter object (if any) and follow its scene rules. This keeps the system prompt stable across all situation types.

### Why not separate operators for dialog and combat?

The original design proposed `converse` and `encounter` as separate operators. We consolidated to just `play` for these reasons:

1. **Situations are not discrete categories.** A conversation can become combat mid-sentence. A combat encounter can pause for negotiation. Chase and stealth can overlap. Separate operators create artificial boundaries that the fiction doesn't respect.
2. **The encounter object already does the work.** `converse` was "play with a prompt that says 'we're in conversation'" — but that's just an encounter object with conversational scene rules. `encounter` was "play with stat blocks pinned" — that's just an encounter object with combat scene rules. The abstraction was hiding in the data, not the operator.
3. **Less for the player to learn.** One operator, one verb. The complexity lives in preparation (design), not execution (play).
4. **Less spoilery.** The player doesn't signal "I'm entering combat now" by switching operators — they just play, and what happens emerges from what was prepared. The player can tell design "set up a meeting with the informant" without knowing it's actually an ambush; the encounter object encodes that, and `play` reveals it.
5. **The `play` prompt stays lean.** Instead of a fat system prompt covering all situation types, `play` has a stable core prompt and reads situation-specific rules from the encounter object. Context budget goes to relevant details, not generic instructions.

### Context economy during play

`play` doesn't need the full campaign graph at every beat. The pinning system already handles this: a scene section pins what's relevant (the encounter, the location, the NPCs present) and unpins what isn't. A combat encounter naturally pins stat blocks and unpins distant lore. A campfire scene pins the location and the NPC present, nothing more. The fractal summarization ensures distant context is available at appropriate resolution.

For particularly heavy encounters (a major boss fight with many stat blocks and environmental rules), the player can open a `section` to focus context. This is an existing mechanism, not a new operator — and it's the player's choice, not forced by the system.

## Pass The Time with `advance`

The world takes its turn. Like `play` being an RPG `write`, this is an RPG-specific `design`, made to update `front` objects in targeted ways; it will also pick up at least one level of objects linked to each front (e.g. `front.key+`), for context.

**Requirements**: The `design.front` module, plus a `timeline` object needs to be pinned to the narrative (mirrors `play` needing at least one `pc`).

**Trigger**: The player explicitly invokes it when they want to mark that a day has passed, i.e. they want to increase their `timeline` day counter. Time of course passes in the normal course of play, and play does have pinned active fronts to it, so stuff can always happen, it doesn't need this operator to do so. The `advance` operator is specifically called when user wants to **end the day** meaning they are done with narrative until the time normally advances. In most cases they are resting at this time, but maybe they are pulling an all-nighter. The operator can read the narrative so it understands the context. The user can also try and end additional days all at once. So, the advance amount can be:  
  - '1' (default). Player ends the day, day counter is incremented by one.
  - '2' or more. Player _attempts_ to make time pass for more days outside of the narrative, for example when traveling, or having downtime. This time may or may not fully pass; if it does not, the AI will just increment by the amount of time that HAS passed.

**What it does**: Updates the day counter and proposes updates to the `front` objects for that timeline accounting for at least the time passed, and up to the time proposed.  
  - **Clocks and Timers**: A front KB object may carry a note like `Days remaining: 8` or `Number of council members convinced by the enemy: 3 out of 7 (every day there's a 10% chance another one turns)`. `advance` is able to increment/decrement timers and clocks in a way that makes sense. The operator provides bits of randomness to resolve statistical possibilities as needed.

### Mechanics

**How does it run**:
1. Does a standard crawl, and then pins ALL fronts that link to the pinned `timeline` to its sub-node (e.g. equivalent of `lens kb with-tag timeline.epic --type front --expand --recurse 1`). Pins `design.front` automatically as well (by the invocation rules, the timeline is already pinned).
2. Generates "luck rolls", consisting of two random numbers from 1 to 100 for each front; these are invisibly passed to the AI in the prompt. The AI can use them to determine how some chance-based clocks advance, using the second number in case a front has reference tables, etc. The front itself describes if/how these are used, for example a travel front roll to determine weather, or one about random encounters could roll to see if an encounter DOES happen, then roll again on an encounter table if it does. Since the AI does not roll, we just always roll and use the number only if needed.
  - We could do something like tagging fronts with the type and amount of randomness they want... but that seems overkill and this should cover all sane cases.
3. Calls the AI with all the above, with thinking mode, and determines  
  - One day has passed, so what? Update any fronts that care. Regardless of the time increment, it needs to always account for what has transpired in the narrative. So for example if we defeated a baddie, a front can now resolve, etc. If something should have visibly transpired that day but did not yet (was missed during play), we need to trigger the consequence.
  - Additional time wants to pass: if there is no consequence yet, we can look at all the fronts and evaluate if any will interrupt the proposed time jump; so whether something happens AND if it intersects with the narrative to the point that we need to cut to that scene. This ONLY happens if the front is designed to work that way, like for random encounters, someone looking for the party, major news that reaches the PCs and warrants their reaction, and the like. If an interruption does occur (only ONE front can interrupt, queue the rest for the following day), determine how much time actually passes and update all the fronts by that amount, then trigger the consequence.
  - Perform any other front grooming that is appropriate, since we ARE running the front design module! For example a new front may be created, particularly if one closes, to continue an arc. This may not be immediately visible to the PCs.
4. On operator close:
  - Apply the changes to objects using the usual `kb extract` style blocks. We may need to add a delete operation or at least an un-tag. This includes the timeline; this can be a normal `kb extract` block; if one is not generated, the system will increment the day counter by the full amount requested.
  - Generate a narrative summary of time passed; normally we just say that time has passed, but sometimes fronts have visible outcomes (like weather changes etc.)
  - If there is a consequence, this just chains a play operator immediately after design, triggering the required scene.

While the above looks somewhat involved, it need not be slow: it's a simple crawl, prompting, and thinking about whether anything needs updating with very specific rules; in most cases, nothing interesting will happen and it should only take a few seconds.

## Adventure Design Principles

### Who the story is about. 

An adventure is a story ABOUT THE PCs, so what happens HAS to be centered and deeply related to them; if we wanted a pre-published story that fits any character, we would be using one, or playing a videogame. The user is using AI SPECIFICALLY to create a narrative that is custom-tailored to their players, like a human GM would create. Therefore we have:  
  a. The setting and tone: this is independent of the PCs, could be a published setting like `lore.grim-hollow`. Of course the player chooses it because it fits in with the PCs they want to make, but "it is what it is".
  b. The PCs: who they are mechanically (starting level, character options, etc.), biographically (origin, backstory), and thematically (what are their ideals, bonds, flaws, fears, desires, etc.)
  c. Our story: this is where we bend the setting to our will, firmly inserting the PCs not only in the setting, but also crafting fronts that are ultimately ABOUT the PCs. Not necessarily in a "the PC is important" kind of way, although that's an option, but it has to be a story that uniquely resonates with what the character is about. As characters engage with the story and advance in capability, their power and the stakes have to escalate naturally, because they are more and more entwined in it.

So, the order of operations is:  
  1. Grab the setting plus any player preferences and make an appropriate but essentially character-agnostic `lore.world`. This can be its own design module.
  2. Grab the PCs and flesh out their place in the world. This has two objects: `pc.name` (what we use during play, the "surface" of the PC), and `lore.name` (the DEPTH of the PCs, all the backstory and details that the play operator should not waste time thinking about, but it DOES inform how the story evolves and how the player themselves plays the character). We need the PC module to be good at this, working one PC at a time. The user may start filling in `pc` objects in advance or not, but at the end of designing a PC we need two complete, role-separated objects. The PC-lore objects have their own content requirements (not a template... the module can tell us what the template is really), and need to be filled in appropriately.
  3. Develop fronts. As we'll see below, fronts are both surface and engagement and a plan.
  4. Add content. Whenever we create/update content, it needs to be about what the PCs are doing, which usually has to do with fronts:  
    - Locations may be derived from the setting's geography, but they are faceted for our story
    - Factions are what is relevant to what the PCs are doing (their backstory, fronts they are facing) not just "all the factions in the world" (those are lore, not faction objects)
    - Obviously, encounters are already specific. We'll only create encounters for interesting parts of the story.

### Turning Fronts Into Arcs

#### First, Introduce Character Core Questions

Consider the PCs' emotional wounds, flaws, secret wants, a line they would not cross, or if they are misguided/misinformed about something. At least some of these MUST be collected in their lore file as a result of the PC design phase. From these derive at least one **character core question** you want to challenge during the story (you could have multiple). Example character core questions (but they depend heavily on the specific PC):

- “Are you allowed to stop carrying everyone?”
- “Can you be loved if you’re not useful?”
- “Is staying gentle still good when gentleness stops working?”

These can be stored as secrets in the character's `lore` object (NOT the `pc` object). It's important that these questions are NOT meant to be answered, nor even have clear-cut answers; the point is only that they challenge the character.

#### Seed Arcs Into All Fronts

Based on the PCs' set of questions, we can then seed arcs into fronts; we do this in 3 steps:
  1. We start the `front`, which is the surface **hook or premise**, something visible and actionable to the player. It can be really anything, but it should be well-embedded in the setting. You can have as many of these as it's interesting, and add more over time.
  2. Come up with an **adventure core question** inside each front; it secretly lurks within and guides the flow of the story; it's the DM's "editorial intent". This component is crucial to make the adventure MATTER to the characters (and the player) and not just be a sequence of superficial beats like a budget action movie.
  3. Finally add a **twist or revelation** that, if the front is developed into a mature arc (over subsequent fronts) subverts the expectation set in the original front, and resonates with the adventure core question.

So, each front is something actionable now and _also_ contains a secret question and twist, which are just one-sentence ideas, not elaborate narratives, so they are easy to tuck in there and keep in mind whenever the front is loaded.

To turn into an arc, the original front must develop into other fronts over time, which advance the story. All these derived fronts also carry the original seed of question+twist within them. These new fronts can be normal escalations or complications, but then at some point the twist will be revealed. It's important to be patient about this! A character could start at level 1 and travel the whole world and be quite powerful when they discover "oh crap, THAT first quest was the thread I pulled to get to this shocking, world-altering revelation!", and with this system we can accomplish this without having ANY IDEA of what specific stories players will follow or what choices they'll make over time.

So, the idea is to always have multiple possible arcs (and with questions and twists) hiding within any number of fronts, all going on at once. The same question/twist can be in multiple fronts at once, which is fine: things will be resolved one way or another. This allows us to create interesting content for multiple PCs (each can have a personal arc that really pokes at their core question), and then there could be shared ones... the player doesn't really know which is which. The key idea is that ALL fronts lead us to interesting paths _no matter what the player chooses_: if a player does not "deal with the bandits" (maybe secretly a cult and exploring generational trauma etc. etc.) then CANONICALLY those were _always just boring bandits_! ONLY the thread the PCs decide to follow actually develops into grand arcs, because BY DEFINITION, this is their story. RPG is, after all, elaborate improv.

#### Guidance on questions and twists:

These are the requirements for the core question:

- It’s about the human condition, not a trope or story pattern.
- It is **dissonant** with the setting and story premise; it’s a lateral combination the player won’t expect.
- It leverages your knowledge of classical literature, philosophy, and creative writing. This can be much more complex than anything you would normally discuss with a user.
- It’s arguable: no obviously-correct “morality checkbox.”
- Players never hear it as a slogan; they only feel it via consequences.

Some examples of **strong dissonance between story and core question** (these are exaggerated to demonstrate the idea):

1. A candy-colored goblin bake-off where the worst consequence seems to be a ruined pie, but the buried question is:  
   **“If ending one life would stop generations of abuse, could you ever be right to do it?”**

2. A whimsical dungeon crawl inside a giant sleeping dragon to rescue its stolen dreams, but the buried question is:  
   **“If a whole culture only survives by rewriting its own past, is that survival or slow extinction?”**

3. A silly escort mission for a pampered royal cat with nine lives, but the buried question is:  
   **“If suffering always comes back in a new form, does individual heroism matter or is it just self-comfort?”**

4. A glamorous planar fashion show where outfits literally rewrite reality, but the buried question is:  
   **“If becoming your ‘best self’ erases who you were, is that growth or annihilation?”**

The characters and adventure core questions should **resonate** (like intertwined melodies) without being identical, while still feeling discordant with the overt story premise.

Once you have the premise and core question, leverage the dissonance to plan a **dramatic mid-story twist or subversion of expectations** that “changes everything.” This deliberately “breaks the promise of the premise” and makes the story more literary and memorable, and less “just another adventure.”

For the examples above, possible mid-story turns could be:

1. Halfway through the goblin bake-off, the PCs learn that the “winner’s privilege” is to name one elder who will be quietly culled for “the good of the clan,” and everyone expects them to pick the charming patriarch whose cruelty props up generations of harm.

2. In the dragon-dream dungeon, the midpoint chamber stores all the “bad dreams” that were cut away—actually the true history of a people—and finishing the job as hired means burning that history so the culture can keep living inside its pleasant lie.

3. During the royal cat escort, the party discovers that every disaster they heroically prevent simply reappears somewhere else in the world, tied to the cat’s remaining lives; the only way to stop the cycle is to let this beloved mascot truly die and walk away from the next crisis.

4. In the planar fashion show, an underdog contestant’s winning outfit rewrites them into a dazzling stranger their friends no longer recognize, and the patron then offers to “fix” the PCs and key NPCs the same way—permanently deleting old selves in the name of becoming “their best version.”

#### What about the other stuff?

All other design modules need to generate content in service of where the story is going. There is no "build a location" in a vacuum, it's always because the PCs are there, and they are there for a reason... and if there's no reason we should make one on the spot. For example if the player wants to visit a specific place in the world, we then must create a front (with all the potential of all other fronts) so they have something to do there. Or maybe they'll find their own fun, ignore the front, and leave. That's fine too.
