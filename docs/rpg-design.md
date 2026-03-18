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

The key design impetus of Lens is to curate and constrain the knowledge set and instructions given to the AI, so it can behave predictably without bloating the context window. Hierarchical summarization makes this already possible with just a bit of user discipline with sections, but when running D&D we have both a large ruleset (baseline knowledge corpus) and demand more from the AI in terms of prompt compliance. We therefore need all the tricks we can to keep context and prompts small and focused.

To this extent, we divide our experience in two alternating phases:  
  - **Planning**: during planning we don't directly generate narrative, we instead reflect on the current state using various methods and with various goals (possibly over multiple LLM calls) with the effect of creating and changing KB objects instead. This can be done directly by the user, with LLM assistance, or by the AI autonomously (depending on the task). Planning can occur in a separate narrative tree for pre-adventure setup, or within a narrative tree (and thus aware of the place in the story) to remember changes, add plans, etc. In-narrative planning may also some details or generate an operator call ("in the morning, you were awakened by...").
  - **Play**: The AI does not update KB objects during normal play, it's too specific of a task. The user can always change objects directly, but it's not something the LLM tries to do, it just focuses on executing. We do what to have triggers and mechanics to switch to planning, however. When we do play, the player may be controlling multiple characters; they need to specify who is acting as if there were multiple people talking at the table. They can 100% just say "Elara wants to..." but it may be more fun for them to pick a character and talk first person: it's where the "Role" part of roleplay comes out. This is orthogonal to operators, so it needs to be supported by Lens, but it's also quite simple because all it does is adds a character marker to the request. 

## RPG Objects Design

We need to design two kinds of objects:  
  1. **Reference Data**: rules and mechanisms that turn free-form writing into playing an RPG
  2. **Types and Templates**: predictable shape of stored that can be leveraged by operators 

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
  3. We use a `front` for everything else. The `advance` operator (the mechanism to update fronts); to use it, we need to **roughly track the passage of time**.

#### The passage of time

We only care about the passage of time in two situations:  
  1. It has a mechanical implication in the game rules, like for rests. Because we are not the game engine, the player is supposed to track time for things like spells, but the AI needs to know roughly the passage of the day for narrative purposes. This should happen organically as the story happens, at most we need to point out in the prompt that this matters.
  2. It advances the story outside of what is happening in the narrative. This is optional: a simple story can have nothing of relevance happening in this way, and even if it does, the AI can just improvise what would have happened on the spot. In some cases where we actually want to tell a story with real pressure, we DO need to track time so the AI can setup and then satisfy expectations. A key fact is that narrative need not be linear storytelling, it can jump back and forth (flashbacks could be a game mechanic!) or the player may want to create multiple parallel narrative trees (split or yet unmet party, or a Westmarch-style campaign); in these cases, the information we accumulate over time in KB may not be accumulative in a simple way. This is a key reason why progress is isolated to `front` objects: they are the only ones that really care about time.

So, how do we track time if we want to do in an advanced way? We follow these rules:  
  1. Each narrative needs to belong to a "timeline", which we can pin to it, e.g. `timeline.alice-prologue`. This object just contains a line for each time the timeline advances; each line should be some kind of point in time that makes sense when compared to its neighbor... that's it. The user advances the timeline by looking at the previous line and entering a new line that states where we are now, so this could be simply dates, but also any granularity they want, from years to rounds.
  2. Each `front` belongs to (that is, is tagged with) the timeline it belongs to, and is advanced when that timeline advances using the `advance` operator (described later).  
    - A front cannot belong to multiple timelines because it needs to advance with it (it's a state, not a log), and also the point is that the narrative can affect. If a user wants to track a rising threat across multiple timelines played one after another, really only the first one could have affected the front, because time has already passed! In reality for these situtations a front would be created only once timelines converge or a timeline "runs into" the front and can deal with it. Casuality is a thing.

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
  - Timeline anchors: if applicable, specific times when something is meant to happen
- Possible resolutions  
  - Specific triggers, states of the worlds, or actions that affect the result
  - Any dependencies on chance, in the form of "every x time there is a y% chance z could happen" (used by advance operator)

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
- Participants: (who's involved; link npc/faction/stat objects)
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
| `design` | Plan | Create/update KB objects via design workflows | As needed |
| `play` | Play | All narrative: prose, dialog, combat, chases, puzzles | Default during play |
| `advance` | Plan | Updates `front` objects as time passes | Player explicitly passes time |

### Create and Refine Knowledge For Your Game with `design`

A dedicated narrative sub-tree where the conversation is not story, it's collaborative design workspace, with KB objects changes are the product. We can start from a dedicate narrative tree, or create a self-closing tag anywhere in the narrative so we have the story so far. Sub-sections may open for dedicated sub-tasks with specialized prompts.

The model emits certainly emits discursive text and collects answers from the user, but the replies also include fenced blocks compliant with the `kb extract` command format. This lets the model focus on content rather than prose style, and makes extraction deterministic. Secrets work because they are encoded as they come out of the LLM.

The operator needs to design objects tailored to play use: concise and appropriately linked and tagged. The player should be able to start playing by pinning an expanded object like `loc.owl-rest-tavern+` or `front.goblin-raids+` and the links (plus the baseline rules and pc pins _should_ be sufficient to get things playing).

The operator _does not_ author static high-level objects like `lore.world` that setup the general setting and tone. Those are added by the player, or they can use a normal edit operator for assistance.

Other Considerations:
  - Ideally we'll want the LLM to perform "scene changes" by using sections with new pins, for example if the tavern is `loc.springfield` by the rules of `loc` there will an edge to it, so when the players leave the tavern the scene can pin Springfield instead.
  - It would be pretty easy to create a `map` operator that uses the `loc` graph to tell the AI what's around, so exploration can lead towards known places. Of course it's ideal to just come up with places as needed by the story, we then just need to decide if they are worth remembering. This goes back to maybe needing non-advance way to remember things.

#### Design objects

The bulk of the knowledge that drives the design flow lives not in the system prompt but in `design` KB objects that can be pinned into the design sub-tree. The root prompt has knowledge of what they are and what's in them, and then asks the user what they want to do: a session zero phase sequence, create or refine objects like locations and factions, create example adventure hooks, plan encounters, etc.

The operator then creates sub-sections that have that type of design task pinned in their front matter, and can even chain a write operator from what the user asked to do to get the section content started without repetition. When the user is done, we simply call `kb extract` on that design sub-folder and import all the knowledge created! The user can of course skip the chat and create a design operator already pointed to a specific design object, and get going right away.

##### Design workflows and their objects

Each design workflow is guided by a `design.*` KB object that the `design` operator pins when the user selects that task. These objects contain instructions for the AI on how to approach that specific build-out task — what to ask, what to look up, what to produce. See the `design.*` objects in the dataset for their content.

| Workflow | Design Object | What it produces | Notes |
|---|---|---|---|
| Session Zero | `design.session-zero` | `lore.world`, initial `loc.*`, `faction.*`, `front.*` | First thing to run for a new game |
| Player Character | `design.pc` | `pc.*` objects from character sheets | Player fills most of this; design helps structure it |
| Location | `design.location` | `loc.*` network with parent links | Geography at any scale |
| Adventure | `design.adventure` | `front.*` with linked `npc.*`, `faction.*`, `loc.*` | The "what happens next" builder |
| Encounter | `design.encounter` | `encounter.*` objects | Prepared situations for play (see below) |
| NPC | `design.npc` | `npc.*` with links and secrets | Recurring characters worth tracking |

#### Encounter objects: the script for `play`

The central design insight: **an encounter object is not "combat." It's any prepared situation.** A conversation that could go wrong, a negotiation with hidden stakes, a chase through a burning building, a combat with tactical complexity, a puzzle with mechanical rules — or any combination of these in sequence or simultaneously. The encounter object is the _script_ that `play` follows.

This is powerful because:
1. **The encounter carries its own rules.** If combat is complex, the object says so and links the relevant stat blocks. If it's a simple bar chat, the object just describes the NPC's goals and what they know. No operator switch needed.
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

The `design.encounter` workflow uses the `balance_encounter` tool for combat encounters specifically: the AI discovers stat block candidates via tags (CR, habitat, type), ranks them by narrative fit, then calls `balance_encounter` to produce balanced proposals. But the encounter object it produces is the same template regardless of whether it's combat, social, or hybrid.

##### How encounters are balanced (combat-specific)

The party has an XP budget from PC levels and chosen difficulty (low/moderate/high); allies reduce that budget. Required monsters are fixed; the tool either fills the remaining budget from optional candidates (weighted by narrative-fit rank) or, if required alone exceed the budget, suggests reduced counts. Encounters can be re-balanced on the fly — situations change, allies join, character levels shift — so the encounter object stores the parameters used, and `design` can refresh the balance without rebuilding the whole encounter.

### Play with `play`

**One operator. Fast, flexible, and prepared.**

`play` is the only narrative operator during play. It receives directorial intent from the player, authors the scene, and maintains the authority model. Whether the current beat is exploration, conversation, combat, a chase, or a quiet campfire — it's all `play`. What changes is not the operator, but the **preparation**: the knowledge objects pinned to the current scene.

When an `encounter.*` object is pinned, `play` reads it as a script: it knows the situation, the stakes, the participants, and the rules for this specific scene. When no encounter is pinned, `play` operates in general mode — the world breathes, NPCs react, and the AI follows the baseline rules in `rules.engagement`. The transition is seamless and invisible to the operator machinery.

**Two postures — not a mode switch, a continuum**:

*Flow*: Default. The AI narrates freely. Scenes develop without requiring stakes at every beat. Not every paragraph needs pressure, and trying to inject it produces a mechanical, exhausting rhythm. The AI should hold flow for extended stretches — walking through a market, sharing a meal, arriving at a new place.

*Stakes*: When risk is live — something can go wrong, a decision is being forced, a check is warranted. The AI establishes what's at risk, names the check type and DC if needed, and narrates the consequence after the player reports results. The AI never describes outcomes before the roll.

Transitions between postures are fluid, driven by the fiction. An encounter object may push toward stakes immediately (an ambush) or start in flow (a conversation that could go wrong). The AI reads the room.

**The authority model in practice**:
- Player input is character intent; the AI authors the attempt and the world's response
- World assertions by the player are treated as character impressions, not confirmed facts, until validated through play
- NPC behavior declared by the player is treated as hoped-for outcome; the AI decides what the NPC actually does
- Declared success is treated as goal, not result; the AI decides if it works or calls for a check
- The AI holds these limits while staying cooperative — the resistance is the world working correctly, not the AI working against the player

**What encounter objects change about play behavior**:

When `play` sees a pinned `encounter.*` object, it uses the encounter's scene rules to calibrate:
- In combat-heavy encounters: state enemy intent before they act, track tactical features, respect the action economy, direct groups by faction behavior
- In social encounters: voice NPCs with their concealed goals, let conversations breathe, call for checks only when the PC pushes past what the NPC would naturally give
- In chase/escape encounters: track distance narratively, introduce complications, respect the exhaustion mechanics
- In mixed encounters: follow the triggers and transitions defined in the object — a negotiation breaks down into combat, a chase ends in a standoff
- In encounters with secrets: the AI knows the secret and plays toward revealing it naturally through the fiction

Without a pinned encounter, `play` defaults to open-world general narration guided by whatever loc, npc, and front objects are pinned.

**System prompt**: The `play` system prompt establishes the GM voice, the authority model, and the gates (ADJUDICATE → NARRATE → RESOLVE → ENGAGE from `rules.engagement`). It does NOT hard-code situation types — it tells the AI to read the pinned encounter object (if any) and follow its scene rules. This keeps the system prompt stable across all situation types.

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

The world takes its turn the player skips time. This is a lot of like `design`, but specifically designed to update `front` objects in targeted ways; it will also pick up at least one level of objects linked to each front, for context.

**Requirement**: A `timeline` object needs to be pinned to the narrative (like `play` neeing at least one `pc`).

**Trigger**: The player explicitly invokes it when they want to mark that time has passed, i.e. they want to update the `timeline`. Passing time is just an entry appended to the timeline, which has to provide a differential time progression from the previous entry. This is generate from two inputs:  
  1. Player stating time has passed. This tracks time that has passed in the narrative, for example at the end of the day of adventuring one can just add "it's night" if the previous entry was "it's dawn".
  2. Player attempts to make time pass outside of the narrative, for example when resting, traveling, or having downtime. So this could be "for an hour", "until morning", or "for 3 days". This time may or may not fully pass; if it does not, the AI will replace this second entry with the time that HAS passed, like "until midnight" or "for 2 days".

**What it does**: Updates `front` objects for that timeline by at least the time passed, and up to the time proposed.

### Guidelines

- **Fronts as drama, not simulation**: A front KB object establishes an expectation — a threat in motion, a clock running, a plan unfolding. `advance` makes that expectation feel real. Two patterns:
- *Story beats*: A front describes what a faction or NPC is working toward in prose. `advance` reads the current state and decides what they've done during the elapsed time, improvising plausibly from what's established. No rules system required — only the established expectation and the elapsed time.
- *Clocks and Timers*: A front KB object may carry a note like `Days remaining: 8` or `Number of council members convinced by the enemy: 3 out of 7 (every day there's a 10% chance another one turns)`. `advance` instructs the AI to notice such elements and increment/decrement timers and clocks in a way that makes sense, and provides a bit of randomness to resolve possibilities. Each of these carries a consequence.
- **Only plan what's been established**. Everything else the AI improvises as if it had been planned all along. Fronts are dramatic expectations, not state machines. The goal is that consequences feel earned, not that anything was actually simulated. This is why we only update fronts... they are the kind of objects that advance.

### Mechanics

**How does it run**:
1. Does a standard crawl, plus loads fronts+ that link to pinned `timeline`. Creates a sub-section for output like `design`. Because timelines can get long, we just pass desired increments to timeline, not the whole object.
2. Generates "luck rolls", consisting of two random numbers from 1 to 100 for each front; these are passed as metadata to the AI, which can use them to determine how some clocks advance, reference encounter tables, etc. The front itself describes if/how these are used.
3. Calls the AI with all the above, with thinking mode, with a prompt to:
  - Looking at all the fronts, evaluate if any will interrupt the _proposed_ time, i.e. if the front intersects with the narrative. This may be very rare (e.g. someone scheming far away) all the way to certain (e.g. a front about frequent raids, where it's most about what than if).
  - Finalize the total time to pass: this will be the sum of what elapsed during narrative plus the total proposed or the cut-off-short time from previous step. This is the final canonical addition to the timeline object.
  - Review all active fronts and decides what happens in each during the total time passed.
  - Generate `kb extract` style blocks to edit fronts.
  - Generate a line to append to the state log; this can be a `kb extract` but Lens will just append the last line.
  - Generating a narrative summary of time passed, and optionally anything the players may have heard about (like rumors or a changing state)
4. Section is closed and summary is emitted. Controls is handed off to the player to continue playing.
  - This may be a great time to also create a checkpoint with the timeline entry added as the message! We do need to have the player approve of it first.

## Starting a New Game: The Cold-Start Problem

Starting a new game in Lens requires enough preparation that `play` has something to work with. Without at least a world frame, a PC, and an opening situation, the AI has nothing to ground — it will produce generic, aimless narrative. This section outlines the minimum viable setup and the process to get there.

### The minimum to start playing

To call `play` and get a meaningful response, you need:
1. **Rules pinned**: `rules.dnd` and `rules.engagement` (provided by the dnd dataset)
2. **A world frame**: `lore.world` — a compact object describing tone, setting, genre, and key constraints. This is pinned at the narrative root and never changes. Created during session zero.
3. **At least one PC**: `pc.<name>` — enough to describe and voice the character. The player fills this from their character sheet.
4. **An opening situation**: at a minimum, a `loc.*` where you are and some sense of what's happening. Maybe an `encounter.*` if we start in media res.

That's it. Everything else — NPCs, factions, fronts, deeper location networks — can be built as you go through `design` sessions between play.

### The setup process

The process has distinct phases, each producing objects that feed the next. The `design.session-zero` workflow guides phase 1–3 in a single design session.

#### Phase 0: Import your setting (optional, manual)

If you have source books (e.g. Grim Hollow), extract or adapt the relevant reference material:
- Extract rules, spells, stat blocks, items via `ddb-extract` or manual creation
- These go into the dataset or project knowledge as reference data
- This is a one-time investment per setting; once done, it's available for any campaign in that setting

#### Phase 1: World frame (`lore.world`)

A compact object (aim for under 500 words) that establishes:
- Setting name and genre (dark fantasy, space opera, etc.)
- Tone and atmosphere (grim, whimsical, gritty, mythic)
- Key constraints (technology level, magic prevalence, social structures)
- What kind of story we're trying to tell (character arc, exploring a theme, or maybe just putting a build through its paces)

This is NOT exhaustive world-building. It's the minimum the AI needs to establish voice and atmosphere. Think of it as the back-of-the-book blurb for the setting.

For deeper world knowledge that `design` needs but `play` doesn't need all the time, create additional `lore.*` objects. Design (unlike play) can use thinking mode and open KB objects, so giving it one or two index objects and letting it work it out is enough.

#### Phase 2: Player characters (`pc.*`)

For each PC, create an object from the `pc._template`. The player has their character sheet — the object captures what the AI needs to describe and voice the character. The `design.pc` workflow helps structure this from a character sheet, asking the right questions and producing a properly tagged object.

#### Phase 3: Starting geography and situation

In most cases, one `loc.*` for where the adventure begins, so we can have a sensory feeling for it. The `design.session-zero` workflow helps here by asking: where are the PCs, what's the immediate situation, what's the first problem they'll face?

This phase should produce:
- 1–3 `loc.*` objects (where you are, what's nearby)
- 0–1 `faction.*` objects (any group relevant to the opening)
- 0–1 `npc.*` objects (anyone the PCs will interact with immediately)
- 1 `front.*` (the first dramatic pressure)
- 1 `encounter.*` (the opening scene)

This is enough to start playing. More objects are built through design sessions as the game progresses.

#### Phase 4: Play and iterate

Once you have the minimum, start playing. After each session (or when the fiction reaches a natural pause), run `design` to:
- Build encounters for the next scenes you anticipate
- Create NPCs and locations as the story demands them
- Update fronts to reflect what happened
- Run `advance` when time passes

The cycle is: **play → design → play → advance → play → design → ...**
