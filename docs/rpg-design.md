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
- **Put the players in interesting and difficult situations so they can use their skills and guile to succeed**: this is the job of `design` — building encounter objects that are fun, fair, and know something the party does not. The encounter object is the DM's prep; `play` is the DM's execution. Material the party must not read yet is either kept in the object's [back](#the-play-surface-and-the-prep-surface), where `play` cannot reach it at all, or encoded in place so it does not read as plain text to the person running `design` (see [What `ai:secret` is for](#what-aisecret-is-for)).

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
    Planning itself splits again, into ideation and artifact design — see [Two prep phases](#two-prep-phases-planning-then-artifacts) below. The split is what keeps the second half honest.
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

### Two prep phases: planning, then artifacts

"Planning" above names the operator mode. Inside it there are two genuinely different jobs, and running them together is what makes prep sessions vague.

**Planning proper** is the ideation: the themes, the arc, the buried question, who this story is about. It produces writing and decisions, not artifacts, and it is deliberately free-form. It can be done entirely by a human, or outside Lens, or in a `design --module planning` session that behaves much more like a coding agent's plan mode than like the other modules — propose, argue, get approval, and only then write anything down.

**Artifact design** invents nothing major. It takes themes and arcs that are already reasonably concrete and turns them into playable objects: fronts that move on their own, balanced encounters, clocks with consequences, NPCs with limits. Its rule is one line:

> **The fiction is given. The mechanism is yours — and inventing it is the whole job, not a fallback.**

Load-bearing story facts are never invented: who someone really is, what a faction actually wants, what the reveal turns out to be. Numbers, triggers, limits, floors, and end conditions always are — nobody hands you "clock 6", and picking it *is* the work. Local colour (a guard's name, what is on the table) is free.

When translation hits something it cannot mechanise without deciding a story fact, the correct move is to **say so and stop**. That report is the only gate in the system, and it is where the human comes back in. It is also why the split pays for itself: a model asked to do both jobs at once will always paper over the missing decision, because it has been given permission to invent stories.

The boundary is kept on purpose rather than automated away. The first phase is a different problem — it wants breadth, taste, and argument — and naming the line produces both better input and a much simpler job for the model doing the second half.

There is deliberately **no `planning` type**. The material lives in whatever type the user likes (`lore.*`, `prep.*`, `plan.*`), because nothing mechanical keys off it. What matters is *where* it lands, which is the next section.

### The play surface and the prep surface

Artifacts have a front and a back.

**The front** is the play surface — what is currently active, driving the present and the immediate horizon. `play` sees this and only this, so by construction it stays small and pertinent.

**The back** is the prep — the whole plot, the next piece to move, why this piece sits where it does. It is still design output, and it is *more* specific than the story material that generated both halves. It must never reach play space. It is an optional addition, not a requirement: sometimes a door is just a door.

#### `-` is a facet separator

The mechanism is a naming convention, not a type. `-` is a hierarchical content separator in KB ids — the UI already treats it as one for autocomplete grouping — and it now means something mechanically:

```
front.problem      front.problem-prep
pc.amy             pc.amy-background
lore.world         lore.world-plots
```

`design` and `advance` **facet-expand**: a root pin also pulls the same-type `<id>-*` objects. `play` does not. Because `lore.world` is pinned at the narrative root, `lore.world-plots` is automatically in scope for every design and advance session and in none of play's — no tagging, no bookkeeping, nothing to remember.

**"Root pin" is really "an id someone named."** A front is the case that makes the distinction matter. It reaches context through `timeline.<id>+`, so it is not pinned and its back does not ride along — but naming it does bring the back, and there are four ways to name an id, all of which honour the rule:

| naming an id | brings its facets |
|---|---|
| ancestor `kb_pin` / `--pin` | ✅ |
| `--module <key>` | ✅ |
| `lens kb get <id> -f` | ✅ |
| the model's own `kb_get` tool | ✅ |

So `advance` and `design --module front` reach a front's back by asking for the front by name — one ordinary `kb_get`, no facet id to guess, no bookkeeping. What is still deliberately excluded is the *unnamed* id: anything arriving by `+`, a tag, a mention, or an include brings no facets, which is what keeps a linked `stat.guard` from dragging in `stat.guard-captain`.

Three of those four surfaces were unwired when the feature shipped; see the note under [Not `+`, and root pins only](#not--and-root-pins-only).

It also works on **missing roots**: `lore.world-geography` and `lore.world-factions` reach design sessions whether or not a `lore.world` object exists, because expansion is a lexical prefix scan over the store rather than a walk over links. Pinning `lore.world` for `play` still pulls nothing — the same pin means "and its prep" to a prep operator and "just this" to everything else.

#### Not `+`, and root pins only

This is deliberately not `+`. `+` expands dot-tag links and works in play space. Facet expansion is implicit, operator-gated, and never typed as a suffix by the user.

**Facets expand for root pins only** — ancestor `kb_pin`, runtime `--pin`, `--module` — and never for ids that arrive via `+`, tags, mentions, or includes. That rule is load-bearing rather than tidy: `-` is already the word separator in 755 objects in `datasets/lens-dnd/`, with 14 genuine collisions between unrelated objects (`stat.guard` / `stat.guard-captain`, `spell.shield` / `spell.shield-of-faith`, `stat.vampire` / `stat.vampire-spawn`, …). Reference objects like those always arrive by expansion or mention, never as root pins — and where one legitimately *is* a root pin, such as a design session that wants every vampire at once, pulling the family is the desired behaviour. So the rule neutralises every collision without a hardcoded type list and without an opt-in tag.

`lens explain` reports facets with their own provenance kind (`'-' facet of front.problem`), so a facet never reads as something the user pinned by hand. `lens kb get -f <id>` applies the same expansion at the command line, with the same root-only rule.

**What shipped, and what did not.** The feature landed with the rule implemented once and applied to two of its four surfaces. Ancestor pins expanded; `lens kb get -f` expanded. `--module` did not — modules never reach the pin resolver, and the transform that does resolve them had no facet handling — and neither did the model's own `kb_get` tool, whose section header claimed it delegated to the CLI's implementation while calling the store directly. The tests that shipped were thorough about the *rule* (root pin yes, `+` link no, unpin wins, multi-level facets) and pinned `front.problem` outright in every case, so nothing exercised the topology a real campaign has — a timeline hub, fronts arriving by expansion, and a model reaching for a back by name. That is why a fully tested feature was unreachable in practice from the two surfaces the model actually uses.

#### The escape hatch stays open

A facet is an ordinary KB object. `@pc.amy-background` mid-scene, or pinning it into an intimate conversation, works exactly as it always did. Deliberate reveals remain available; accidental ones stop.

#### What `ai:secret` is for

The facet split is about *scope*: the back is invisible to `play` because it is never assembled into the prompt. `ai:secret` is a different and much smaller thing, and the two got conflated as guidance accreted around them.

`ai:secret` encodes an HTML comment so it does not read as plain text to a human scrolling the file. That is the entire guarantee. It defends against casual peeking by the person at the keyboard — who is, after all, both the GM and the player here — and against nothing else. It is not access control, it is visible to every model that reads the object, and nothing may be built on it staying hidden.

That was always the intention, and the guidance around it grew well past it. So it is now confined to the `md_html_comments` modality, which a project can turn off outright — and when it is off, no prompt mentions it at all. **No design module, template, or operator prompt references it.** The one genuinely good use is small and scene-local: a fact the current beat will settle either way, like which door is trapped or whether the offer is genuine. A model that has the modality will reach for it there on its own, because it is obviously the right shape; asking for it in ten modules only produced ten places for the claim to grow.

The corollary matters more than the mechanism: anything whose secrecy is load-bearing over time belongs in the back, not in an encoded comment.

#### What this gives `advance`

`advance` has always had a conflict about what it is supposed to invent as time passes. The front/back split resolves it: **nothing**. It modifies what is in play only by pulling from what is prepped, and it does not need to go looking — by convention, and critically by how `design` is instructed to operate, if an object is in scope then its prep arrived with it. Promoting a piece of the back into the front's visible text is the main thing `advance` does. When a front runs out of prep, it says so in the summary and leaves the front alone; the user runs a design session.

### Artifacts, Modules, Rules, and Templates

Four things carry the weight of RPG prep, and they are constantly confused with one another. The distinction is worth being pedantic about, because each is read by a different consumer at a different time.

**An artifact** is the thing prep actually produces: something named, with a shape you can check, content you can act on, and a presence the player can feel. A concession budget. A walk-away condition. A clock with a stated consequence per tick. An alarm that means *reinforcements*, not *detection*. The first test is whether a play operator, mid-beat, can look at it and find it either satisfied or not. "Let the conversation breathe" fails that test — it is guidance, and guidance evaporates under pressure. "Two concessions, then he walks" survives it.

The second test is **perceivability**, and it is the one that gets skipped. `play` must be able to check the artifact; the *player* must be able to feel it. A concession budget nobody can sense is fiat with extra steps — the scene plays out identically whether or not it exists, and the player never gets to push against it. This is also the one thing encounter balancing cannot buy back: a fight tuned to the last hit point is still arbitrary if nothing tells the party which way it is going. So every artifact needs a tell: the pause before the third question, the shuttered shop, the price named out loud, the visible tick.

An artifact does **not** have to be its own KB object, and usually should not be. One concrete line inside the encounter is an artifact.

**A design module** (`design.*`) is instruction for making one: the stance to take, the structure to fill, what makes a good one, worked examples, and what it is not. A module is not ready until it names an artifact and says how to check it. Modules are read by `design`, never by `play`. `design.planning` is the deliberate exception — it produces the material the others build from, and its output is not an artifact at all.

**A rules booklet** (`rules.*`) is how to *use* an artifact once the scene is live: how to engage with it, which triggers bring it into play, what a full clock means procedurally. A booklet is written for `play`. `design` reads booklets too — it has to, since it is authoring an object that will be read against them — but it writes *against* a booklet, never *out of* one, and nothing a booklet says should end up copied into an emitted object. Not every artifact needs one — sometimes the usage is obvious, and sometimes stating usage right next to the definition is simply easier for a model to associate than a separate document would be. So a `rules.*` object may not exist at all, or may exist mainly as a shelf of ready-made phrasings to quote next to an artifact.

**A template** (`<type>._template`) is the shape of a stored object: fields, ordering, tag policy. Templates and modules overlap by design — the template is the target, the module is how to get there well. One thing to be clear about: the fenced `kb` blocks a design session emits do **not** pass through the template machinery. The template is *just more prompt*. That is an advantage, not a gap: it means several templates can be read in one session and their artifacts landed in a single object, whenever that is the only place they are ever relevant.

#### Mixing

Both axes mix, and the system is much less useful if they do not.

*Several modules, one session.* `design --module encounter --module npc` runs one session against both, with both templates in scope. A prepared scene is usually several artifacts — the situation, the antagonists, the clock that paces them — and splitting that across sessions splits exactly the context that makes them fit together. Passing `--module` again *replaces* the set, so a session can be narrowed back down.

*Several artifacts, one object.* The default is to write everything the scene needs into the object the scene will pin. An encounter can carry its own antagonist notes, its own clock, and its own social ladder out. Split an artifact into a separate object only when it earns the split: it outlives the scene, it is reused elsewhere, or it is long enough to bury what surrounds it. When you do split, tag it on the parent so `encounter.foo+` still carries it.

Lens de-duplicates the result. Rules for a type arrive automatically for objects actually in scope — an encounter containing `stat.*` blocks brings `rules.stat` with no tagging and nothing to remember — and a booklet reached twice through two different links is still rendered once.

#### The regression to guard against

Give a design module permission to write running advice into its artifact and it will, sooner or later, re-explain the whole procedure. The rule is **deltas only**. `rules.encounter` already covers how to run a prepared scene; the object states what is different about *this* one — the numbers, the triggers, the exceptions — and never restates how clocks work.

This is not a tidiness argument. A re-explained rule is a second copy that drifts from the booklet, and at play time the model has no way to tell which copy is authoritative. It is also why the deltas rule survives contact with the token budget: a play beat with a prepared encounter runs roughly 14k tokens, of which the rules booklets are about 82% and the encounter itself under 200 tokens. The object is not where you save space; it is where you say the thing no booklet could know.

### Reference Data

#### Rules

Operators pin the core rules plus any system-specific rules they need. We do NOT need all the rules of a game in our rules corpus, because the AI _does not always play the entire game_ (it's not a game engine). In particular all the rules for creating player characters don't usually belong here (they are _at most_ design modules). 

We create two core rule objects:  
  - `rules.rpg`: our AI-player contract; core layer, ruleset-agnostic
  - `rules.system`: system-specific rules. Lens ships with a Lens edition of *Lasers and Feelings* (CC BY 4.0 – John Harper, 2013), a one-page ruleset tuned for AI use, but it can be overridden by a game system ruleset by simply replacing that object id in a higher-priority dataset — which is what the bundled `lens-dnd` dataset does.
    - `rules.*`: some systems benefit from having multiple rulesets for different phases of play (e.g. Blades in the Dark's downtime, D&D's Bastions, etc., very specific combat rules like in some Powered by the Apocalypse games). In these cases the system rules can just be the foundation, and then the player can alternate phases by splitting the rules and pinning as needed. This is the parallel to `design` having different modules for different things you can work on.

##### Who asks for a rules module

`play --module <key>` puts the choice on the player, which is backwards for the common case: the player is directing, not writing, and often does not know the scene is about to become combat. A dataset can therefore **register** its rules modules in its own `lens.toml` (`[[dataset.modules]]` with `operators = ["play"]` and a description of when the module is needed — see [configuration.md](configuration.md#datasetmodules-dataset-lenstoml)), and the model may pull one into scope with the `load_module` tool before it replies. It gets the text in time to use it in that same beat, and Lens writes an `include` annotation so the module stays in scope for the rest of the node. It is offered only while it is out of scope, so this costs at most one round trip per module per node.

Prepared content should still pre-declare: tag an encounter with the rules module it uses and `encounter.*+` expansion loads it deterministically at pin time, leaving the tool to cover only the transitions nobody planned. And there is no unload: when the fight is over, `collate` the range into a sub-node (the annotations travel with the prose) or `--end` the session — the same moves you would make anyway.

##### Which rules earn a module

Registering everything that *could* be needed recreates the problem: an unloaded module costs a catalog line on every beat, in the tool schema and again at the tail of the task. The test is **system or situation**.

A **system** is big, structured, self-contained, and announces itself in the fiction — a fight, a pursuit. It earns a module. A **situation** — one hazard, a sea voyage, a specific negotiation, a crafting project — is known at prep time, is usually small, and differs every scene. It has no reliable trigger the model could recognise, so it travels inside the prepared object instead, either quoted into the scene rules or tagged so `encounter.*+` brings it along.

That leaves two more routes worth naming, neither of which costs a per-beat line:

- **`rules.<type>` companions.** `<type>._template` tells `design` how to *create* an object of a type; `rules.<type>` tells `play` how to *use* one, and `RulesCompanionTransform` adds it whenever any `<type>.*` object is pinned. Convention only — ship the file and it activates. This is where per-type guidance belongs instead of being repeated in every object.
- **Rules on a design module.** Module pins resolve with `+`, so tagging a rules object on `design.<key>` puts it in the crawl when the session opens. Link only what *every* session of that kind needs — the base ruleset, plus the runtime procedure the authored object will be read against — and **list** the rest inside the module text. `design` has `kb_get`, runs a handful of turns, and knows by then what sort of scene it is building; a user who already knows can skip even that with `--include rules.combat` or an `@rules.chase` in the opening prompt. Linking the whole shelf just moves the always-loaded problem from `play` to `design`.

  The listing has to be honest about which is which. If the module text describes an optional object in terms that make it sound always relevant, no model will decline to fetch it, and you have paid for a tool call to reach something you should simply have linked. Either it is always needed — link it — or say plainly when it is not needed.

  Rules objects must not tag *each other*, or `play --module <key>` will drag the links in too.

#### Reference Objects

Reference materials are different than rules proper because they are **lists of items only relevant if in play**, and even if in play, they may not be that relevant in narrative. In other words, the AI doesn't need to know about a creature stat block until it's in play, or about a special ability until something in scene can use it or the player invokes it.  
  - We may be tempted to, for example, include every ability known to a character on their object, but this will just tempt the AI to make the character _do those things_, because we gave it the option. For NPCs we DO want the AI to know and select from the stat block's abilities, so it's best to just tell the AI to use what it sees, and keep those details out when we want the player to activate them. So if a player uses an ability they can resolve attacks, saves, or other checks at the table, report narratively what happened, and move on; however if we want the AI to _really_ engage with that ability, or there are interesting consequences, or it reveals information only the AI should adjudicate, we need to put the reference in context. In those cases the player can `@` the relevant KB object (e.g. in a fantasy rules corpus: "Alice casts @spell.detect-magic, what does she see?") and the AI gets the full details, can show the character using it, and can describe the results. 

To develop these objects, we just need to extract the text from the rulebooks and format them consistently. These are not really used by operators, but they are useful prompt context. For example in D&D we can track object types like:  

  - `spell` one object per spell, full details. We don't really need "indexing" by level, school, etc. as the AI doesn't need to find them.
  - `stat` blocks (monsters and similar, but we won't want to bias the AI); mostly full details but we need to format the stat block consistently, and some details and tables may not be necessary. As an extra complication, planning needs to find creatures for encounters, so some indexing by tag will be necessary. This is quite easy to do with pattern matching. For games that use them, fields like challenge rating and habitat are good candidates for tags.
  - `feature` objects cover character (species or class) features that are relevant to mention because (much like a spell) are actively triggered, cause an interesting narrative effect, and are complex enough that explaining why/how you can do that would be tedius or unclear, and also they are too involved to just have in the PC stack block all the time. Features like "can breathe underwater" or "add more damage", or "do extra attacks" would not have a feature entry because the AI does not run combat.
  - `item` will cover magic items, and `equipment` more normal items you can find often or in stores. These are not necessary unless the AI can find them and put them in the world as loot or store inventory for the players, and this is not very easy to do! We can use type/tags, rarity/GP cost and create a custom prompt to search for them, much like we do for stat blocks. 

#### Using tags

So, you cast `@spell.fly` and you fly, but later the AI forgets you are flying or who is flying and not flying (maybe it's a different scene and this fact may literally be lost in the summaries), so now you have to rollback and add to your prompt that "remember I was flying" and the AI doesn't even see your past prompts, so this may become endemic and not fun. We don't want to manage state nor micro-manage editing objects all the time for that, but what if we used tags for "micro-state", things like conditions or roughly single-word mechanical rules applied to a character? This like putting condition rings on your mini, and would be mostly on the user to track (when things actually do apply and get removed is quite complicated... we have counter-spells, saving throws, concentration checks, durations...) but even then saying `kb tag pc.alice -a speed:flying -a concentrating` is not super-hard, and because these are all rules, the words are limited and easy to auto-complete in a UI. Now the AI and the user can both know you are flying and concentrating (tricky to remember at the table!). 
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
   1. Each narrative needs to belong to a "timeline", which we pin to the narrative root with the `+` suffix (e.g. `timeline.epic+`). This object contains a starting reference and a **day counter**. The user advances the timeline using `advance` which increments the day counter.  
     - The day counter moves forward every day at the same time; in a modern setting it could be midnight, in a fantasy one it could be a dawn. It doesn't have to be perfect as long as it's self-adjusting.  
     - The `+` suffix is critical: it triggers a one-hop expansion of the timeline's tags, pulling in all active fronts (and optionally tagged supporting objects) into narrative context.  
   2. Each `front` belongs to one timeline. Fronts are linked to timelines via tags ON THE TIMELINE OBJECT (not on the front itself). The timeline lists its active fronts as dot-tags (e.g. `tags: [front.goblins, front.drought]`).  
     - A front cannot belong to multiple timelines because it needs to advance with it (it's a state, not a log). If a user wants to track a rising threat across multiple timelines played one after another, really only the first one could have affected the front, because time has already passed! In reality for these situations a front would be created only once timelines converge or a timeline "runs into" the front and can deal with it. Causality is a thing.
     - To run time-overlapping narratives, the user can simply create multiple timelines with the same start reference time, and start them at different day numbers, advancing them whenever they play that narrative.
   3. **Lifecycle**: `advance` updates front content (clocks, phases, resolution notes) but NEVER changes which fronts are active. `design --module front` handles the lifecycle: creating a new front tags it on the timeline; closing a front removes its tag from the timeline. This separation ensures resolved fronts stay in context for planning the next problem.

## RPG Object Templates

Object templates, field descriptions, and tag policy live in `datasets/rpg/knowledge/` — one `_template.md` per type (`pc.*`, `npc.*`, `location.*`, `faction.*`, `front.*`, `lore.*`, `encounter.*`, `timeline.*`). A system dataset adds templates for the types it introduces and may shadow a core one where the system needs a different shape: `lens-dnd` ships `stat.*`, `spell.*`, `equipment.*`, and `tracker.*`, and replaces `encounter._template` with a sectioned version that carries a stat-block roster.

Templates are read by `design` as prompt, so a template earns its length the same way a module does. The short ones (`lore`, `pc`) are fields and a tag policy; the long ones are really authoring instructions that happen to live next to a shape.

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

Fenced `kb` blocks use YAML front matter (`id`, optional `tags`, optional `remove-tags`) and a Markdown body. The body **replaces** the stored object when it is non-empty (after trimming leading/trailing whitespace). If the body is empty or whitespace-only and the object **already exists**, extraction **does not** change the stored text—it only applies tag additions and removals. That lets you link objects (e.g. add a parent `location.*` tag) without re-emitting full content. For a **new** id, an empty body still creates the object with empty content (and tags are applied as usual). Tags listed under `tags` are always **additive**; removing a tag requires `remove-tags`, never replacing the whole tag set via the block alone.

The sub-node is created automatically on the first call, with an ID derived from the prompt and module (e.g. `design-encounter-the-bridge-ambush`). Subsequent calls detect the active session and add blocks rather than creating a new sub-node. This lets the user refine across multiple exchanges before committing.

The operator needs to design objects tailored to play use: concise and appropriately linked and tagged. The player should be able to start playing by pinning an expanded object like `location.owl-rest-tavern+` or `front.goblin-raids+` and the links (plus the baseline rules and pc pins _should_ be sufficient to get things playing).

Static high-level material — `lore.world`, the arcs, the buried questions — is not artifact design and does not belong to the artifact modules. The player can write it by hand, bring it from outside Lens, or work it out in a `design --module planning` session; the artifact modules then read it and never re-derive it.

Other Considerations:
  - Ideally we'll want the LLM to perform "scene changes" by using sections with new pins, for example if the tavern is `location.springfield` by the rules of `location` there will be an edge to it, so when the players leave the tavern the scene can pin Springfield instead.
  - It would be pretty easy to create a `map` operator that uses the `location` graph to tell the AI what's around, so exploration can lead towards known places. Of course it's ideal to just come up with places as needed by the story, we then just need to decide if they are worth remembering, which can do with the `remember.*` system.

#### Design Modules

Each design module is a `design.*` KB object that contains instructions for the AI on how to approach a specific build-out task — what to ask, what to look up, and above all which artifact to produce. Selecting a module with `--module <key>` records `design.<key>` on the session's open annotation so it resolves into every subsequent call's context, together with its `+` links, its `-` facets, and its `<key>._template`.

`design.planning` is the one module that does not name an artifact, because it is the other phase: it produces the material the artifact modules consume. It is also much more interactive than the rest — it proposes, argues, and emits `kb` blocks only once the user has approved a plan. That gate is requested clearly and not enforced anywhere, which is the right trade for a low-stakes problem: the cost of an unapproved emission is an object the user edits or deletes.

The flag repeats. `--module encounter --module tracker` runs one session against both modules and both templates; passing `--module` again on a later call *replaces* the active set rather than appending, so the flag always reads as "these are the modules now". Keys are validated before anything is written, so a typo in the second module cannot open a session against only the first.

When the user is done with a design session, `lens design --end` runs `kb extract` on the full sub-node and imports all the generated KB objects. Each call to `lens design` adds a new inline block to the sub-node; the user can refine progressively across multiple calls. You can start with no module for an open-ended session, or go straight to a specific task — `lens design "build the ambush" --module encounter` creates a sub-node with `design.encounter` already in scope.

**Discovery, not a list.** Modules are found, never enumerated in prose. A bare token naming a type matches every object of that type, so `kb_with_tag ["design"]` returns every design module there is, each printed with its first three lines. That is why the [first-three-lines policy](#the-first-three-lines) is load-bearing: those lines are the entire basis on which a module is chosen or skipped. `design` can also reach a module mid-session with `kb_get design.<key>`, which returns `<key>._template` alongside it — templates are not tagged, so a tag search alone would never find them.

A hand-maintained list of modules pasted into some modules and not others is the thing this replaces. Such a list goes stale silently, and a stale discovery list is worse than none: the modules missing from it are invisible rather than merely unlabelled.

Design module definitions live in `datasets/rpg/knowledge/design/`, with system-specific overrides in the system dataset (`datasets/lens-dnd/knowledge/design/`).

#### The first three lines

Every design module, rules booklet, and template opens with at most three lines containing only its name or title, its purpose and when it applies, and whitespace. Nothing else. This is a content convention with two mechanical consumers, so it is not decorative:

1. `kb_with_tag` prints those lines under every match, which is how `design` chooses between modules it has not read.
2. `[[dataset.modules]]` uses them as the `load_module` catalog entry, instead of a description duplicated into `lens.toml`. A registered module whose opening lines do not say what it covers and when to load it is, in practice, not offered.

The convention costs nothing on most objects because they already look like this — a stat block opens with a name, a spell with its name and level. It matters most on the long instructional documents, which are exactly the ones that tend to open with a section heading instead.

#### Encounter objects: the script for `play`

Key tenet: **an encounter object is not "combat." It's any prepared situation.** A conversation that could go wrong, a negotiation with hidden stakes, a chase through a burning building, a combat with tactical complexity, a puzzle with mechanical rules — or any combination of these in sequence or simultaneously. The encounter object is the _script_ that `play` follows.

This is powerful because:
1. **The encounter carries its own rules.** If combat is complex, the object says so and links the relevant stat blocks. If it's a simple bar chat, the object just describes the principal NPC's goals and what they know. No operator switch needed.
2. **Situations mix naturally.** An encounter that starts as dialog can have a secret trigger for combat. A chase can pause when the quarry turns to negotiate. The object describes the full possibility space; `play` navigates it.
3. **The object knows more than the player.** The player can tell `design` "I'm going to the bridge to meet the informant" and the encounter object can hold that the informant is actually an ambush. What the player reads is the design conversation, not the emitted object. During play, the AI sees the encounter and acts accordingly.
4. **Reuse and adaptation.** An encounter object can be re-used (the patrol at the checkpoint is the same every time) or adapted (the party's reputation has changed, so the guards react differently — update the encounter or let `play` figure it out from the pinned front).


### Play with `play`

**One operator. Fast, flexible, and prepared.**

`play` is the only narrative operator during play. It simulates a conversation between the player (possibly acting in-character) and the GM; the AI listens to what the player says (this is part of the stored conversation, its NOT simply hidden directorial intent like in `write`), authors the scene, and maintains the authority model. Whether the current beat is exploration, conversation, combat, a chase, or a quiet campfire — it's all `play`. What changes is not the operator, but the **preparation**: the knowledge objects pinned to the current scene.

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

Without a pinned encounter, `play` defaults to open-world general narration guided by whatever location, npc, and front objects are pinned.

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

The world takes its turn. `advance` is a **content-only** operator: it changes what objects say, never which objects exist or which are active. Active fronts are determined by the timeline's tags, and only `design --module front` manages those.

**It is not fronts-only.** Fronts are the common case, but the job is *everything time was waiting on*: a clock inside an `encounter.*`, a `state`-tagged tracker, a faction operation with a stated schedule, a construction that takes six days. The test is whether the object's own body says what a day costs it — if it does, that statement is the instruction, and `advance` is the only pass in the system that reads it. Restricting it to `front.*` was never a mechanical constraint (`kb_extract` applies any block); it was the prompt being narrower than the operator.

**It invents nothing.** This was the operator's long-standing ambiguity — how much is it allowed to author as time passes? — and the front/back split answers it: nothing at all. `advance` changes what is in play by pulling from what is prepped. It does not have to go looking for that prep, because facet expansion puts each front's `-prep` facet in its context alongside the front itself. Promoting a prepared piece into the front's visible text is the main move; marking that piece spent in the facet is the bookkeeping. A front that needs a development nobody prepared gets its stated mechanics advanced and a line in the summary saying it is out of prep, and nothing else.

**Requirements**: a `timeline.*` object pinned on an ancestor node (typically at the narrative root with `+` suffix — any form satisfies the check). Nothing else: `advance` pins **no module**. It is spawned as a child of the narrative node that already carries the fronts, and having one job means there is nothing for a module to select between — the procedure lives in `advance.system`. Like `design`, it sets `expand_facets`, so every root pin brings its `-` facets.

**How fronts reach context**: The user pins `timeline.<id>+` at the narrative root. The `+` suffix triggers a one-hop expansion that follows the timeline's dot-tags, pulling in all tagged front objects (and any tagged supporting objects). No explicit front pinning is needed — the timeline is the hub.

**Trigger**: The player explicitly invokes it when they want to mark that a day has passed, i.e. they want to increase their `timeline` day counter. Time of course passes in the normal course of play, and play does have pinned active fronts to it, so stuff can always happen, it doesn't need this operator to do so. The `advance` operator is specifically called when user wants to **end the day** meaning they are done with narrative until the time normally advances. In most cases they are resting at this time, but maybe they are pulling an all-nighter. The operator can read the narrative so it understands the context. The user can also try and end additional days all at once. So, the advance amount can be:  
  - '1' (default). Player ends the day, day counter is incremented by one.
  - '2' or more. Player _attempts_ to make time pass for more days outside of the narrative, for example when traveling, or having downtime. This time may or may not fully pass; if it does not, the AI will just increment by the amount of time that HAS passed.

**What it does**: Updates the day counter and proposes updates to the `front` objects for that timeline accounting for at least the time passed, and up to the time proposed.  
  - **Clocks and Timers**: A front KB object may carry a note like `Days remaining: 8` or `Number of council members convinced by the enemy: 3 out of 7 (every day there's a 10% chance another one turns)`. `advance` is able to increment/decrement timers and clocks in a way that makes sense. The operator provides bits of randomness to resolve statistical possibilities as needed.
  - **Does NOT close or retire fronts**: If a front reaches resolution, `advance` notes it in the summary block. The player runs `lens design --module front` to close the front (remove its tag from the timeline) and create the next pressure. This keeps the resolved front in scope for the LLM when designing what comes next.

### Mechanics

**How does it run**:  

  1. Builds **context**: Fronts are already in the crawl — pinned on the narrative, or reached from the ancestor-chain `timeline.<id>+` expansion (the timeline's dot-tags list active front IDs, which `+` expansion follows). A pinned front brings its `-` prep facet; an expanded one gives it up to a `kb_get`. No module is pinned. **Narrative** uses a **narrative slice** (see `design.md` § *Narrative slices*) anchored at the previous completed `advance` for the same timeline, rather than a standard full-ancestor crawl. This gives the AI exactly the fiction that transpired since the calendar last moved — enough to update fronts and evaluate interruptions — without the full story-so-far that `play` needs. See *How `advance` finds its anchor* below for how the anchor is located and validated.
  2. Generates "luck rolls", consisting of two random numbers from 1 to 100 for each front in the crawl (filtered from the pinned IDs); these are invisibly passed to the AI in the prompt. The AI can use them to determine how some chance-based clocks advance, using the second number in case a front has reference tables, etc. The front itself describes if/how these are used, for example a travel front roll to determine weather, or one about random encounters could roll to see if an encounter DOES happen, then roll again on an encounter table if it does. Since the AI does not roll, we just always roll and use the number only if needed.
  3. Calls the AI with all the above, with thinking mode, and determines  
    - One day has passed, so what? Update any fronts that care. Regardless of the time increment, it needs to always account for what has transpired in the narrative. So for example if we defeated a baddie, a front can now resolve, etc. If something should have visibly transpired that day but did not yet (was missed during play), we need to trigger the consequence.
    - Additional time wants to pass: if there is no consequence yet, we can look at all the fronts and evaluate if any will interrupt the proposed time jump; so whether something happens AND if it intersects with the narrative to the point that we need to cut to that scene. This ONLY happens if the front is designed to work that way, like for random encounters, someone looking for the party, major news that reaches the PCs and warrants their reaction, and the like. If an interruption does occur (only ONE front can interrupt, queue the rest for the following day), determine how much time actually passes and update all the fronts by that amount, then trigger the consequence.
    - Note resolution in the summary if any front reaches its final phase. Do NOT create, retire, or un-tag any front.
  4. On **`advance --end`** (with the cursor in the advance sub-node):
    - Apply the content changes to fronts using `kb extract` style blocks. No tag changes are applied to fronts or timelines by advance.
    - Increment the timeline's day counter.
    - Append a narrative summary of time passed to the parent; normally we just say that time has passed, but sometimes fronts have visible outcomes (like weather changes etc.). If there is a consequence, this is also narrated, so the user can react with a `play` operator call.

While the above looks somewhat involved, it need not be slow: resolving pins and the slice, then prompting, is still bounded work; in most cases, nothing interesting will happen and it should only take a few seconds.

### The advance → design handoff

Advance and design are deliberately separated:

| Aspect | `advance` | `design --module front` |
|--------|-----------|------------------------|
| Updates front content | Yes | Yes |
| Promotes prep into the front | Yes | Yes |
| Invents new developments | No | No (that is `design --module planning`) |
| Creates fronts | No | Yes |
| Retires/removes fronts | No | Yes (removes timeline tag) |
| Manages timeline tags | No | Yes |
| Tags supporting objects on timeline | No | Yes (optional) |

This separation ensures that when a front resolves, it stays in scope for the design session that creates the next pressure — the LLM can see what just completed and design a worthy successor. The player's workflow is: play → advance (fronts evolve) → play → advance → ... → design (close resolved front, create next) → play → ...

### How `advance` finds its anchor

`advance` uses the narrative slice mechanism (see `design.md` § *Narrative slices*) to collect only the fiction that transpired since the calendar last moved. The standard full-ancestor crawl that `play` uses would waste context on distant material irrelevant to front updates.

**Finding the anchor:** The search is scoped to the **same `timeline`** that will advance. Starting from the cursor, walk **backward in narrative reading order** (sibling order derived from parent markdown, then filesystem tie-break). On each node, scan its segments in reverse for a **completed** `advance` annotation (one with a matching `timeline` param and a close tag). Stop at the first match.

**Validation:** Each advance annotation records `current_day` (the starting day) and `increment` in its params. The sub-node’s output may contain a `days_elapsed` field (when the time jump was interrupted); otherwise, the full increment is assumed. The anchor is valid only if `start_day + days_elapsed == current_day` (the timeline’s day counter before this new advance). This ensures the anchor is the session that actually landed the calendar on “today.” If validation fails, the operator raises an error — the timeline may have been edited manually.

**First advance:** If no prior completed advance exists for that timeline, `find_advance_anchor` returns `None` and `crawl()` falls back to a standard full-ancestor crawl (equivalent to a slice from the narrative root).

**What gets collected:** The slice boundary starts immediately after the previous advance’s close tag (the `line_end` of the `SliceAnchor`). From there, `crawl()` walks the spine to the cursor, collecting text from each node on the path — partial text on the anchor node, full text on intermediates, and the cursor node as `current_content`. KB pin resolution always uses the full ancestor chain regardless.

## Adventure Design Principles

### Who the story is about. 

An adventure is a story ABOUT THE PCs, so what happens HAS to be centered and deeply related to them; if we wanted a pre-published story that fits any character, we would be using one, or playing a videogame. The user is using AI SPECIFICALLY to create a narrative that is custom-tailored to their players, like a human GM would create. Therefore we have:  
  a. The setting and tone: this is independent of the PCs, could be a published setting like `lore.grim-hollow`. Of course the player chooses it because it fits in with the PCs they want to make, but "it is what it is".
  b. The PCs: who they are mechanically (starting level, character options, etc.), biographically (origin, backstory), and thematically (what are their ideals, bonds, flaws, fears, desires, etc.)
  c. Our story: this is where we bend the setting to our will, firmly inserting the PCs not only in the setting, but also crafting fronts that are ultimately ABOUT the PCs. Not necessarily in a "the PC is important" kind of way, although that's an option, but it has to be a story that uniquely resonates with what the character is about. As characters engage with the story and advance in capability, their power and the stakes have to escalate naturally, because they are more and more entwined in it.

So, the order of operations is:  
  1. Grab the setting plus any player preferences and make an appropriate but essentially character-agnostic `lore.world`. This is planning, not artifact design: it belongs to `design.planning` (or to the user's own notes), and whatever is too heavy for a play-pinned object goes into `lore.world-*` facets that only prep sessions ever see.
  2. Grab the PCs and flesh out their place in the world. This has two objects: `pc.name` (what we use during play, the "surface" of the PC), and `lore.name` (the DEPTH of the PCs, all the backstory and details that the play operator should not waste time thinking about, but it DOES inform how the story evolves and how the player themselves plays the character). We need the PC module to be good at this, working one PC at a time. The user may start filling in `pc` objects in advance or not, but at the end of designing a PC we need two complete, role-separated objects. The PC-lore objects have their own content requirements (not a template... the module can tell us what the template is really), and need to be filled in appropriately.
  3. Work out the arcs — the questions, the twists, what each thread is really about — then develop fronts from them. Those are two steps, not one: the first is planning and the second is scheduling. A front is the surface and the engagement; the plan behind it lives in its `-prep` facet.
  4. Add content. Whenever we create/update content, it needs to be about what the PCs are doing, which usually has to do with fronts:  
    - Locations may be derived from the setting's geography, but they are faceted for our story
    - Factions are what is relevant to what the PCs are doing (their backstory, fronts they are facing) not just "all the factions in the world" (those are lore, not faction objects)
    - Obviously, encounters are already specific. We'll only create encounters for interesting parts of the story.

### Turning Fronts Into Arcs

Everything in this section is **planning**, and it lives in `design.planning`. `design.front` deliberately does not carry it: a module that both invents themes and schedules pressure will always do the first badly and skip the second. Front grooming asks how much of this material is live right now and what makes each live piece checkable; where the material came from is not its problem.

#### First, Introduce Character Core Questions

Consider the PCs' emotional wounds, flaws, secret wants, a line they would not cross, or if they are misguided/misinformed about something. At least some of these MUST be collected in their lore file as a result of the PC design phase. From these derive at least one **character core question** you want to challenge during the story (you could have multiple). Example character core questions (but they depend heavily on the specific PC):

- “Are you allowed to stop carrying everyone?”
- “Can you be loved if you’re not useful?”
- “Is staying gentle still good when gentleness stops working?”

These are stored in the character's `lore` object (NOT the `pc` object) — the PC's back, which never reaches a play beat. It's important that these questions are NOT meant to be answered, nor even have clear-cut answers; the point is only that they challenge the character.

#### Seed Arcs Into All Fronts

Based on the PCs' set of questions, we can then seed arcs into fronts; we do this in 3 steps:
  1. We start the `front`, which is the surface **hook or premise**, something visible and actionable to the player. It can be really anything, but it should be well-embedded in the setting. You can have as many of these as it's interesting, and add more over time.
  2. Come up with an **adventure core question** inside each front; it secretly lurks within and guides the flow of the story; it's the DM's "editorial intent". This component is crucial to make the adventure MATTER to the characters (and the player) and not just be a sequence of superficial beats like a budget action movie.
  3. Finally add a **twist or revelation** that, if the front is developed into a mature arc (over subsequent fronts) subverts the expectation set in the original front, and resonates with the adventure core question.

So, each front is something actionable now and _also_ carries a buried question and twist, which are just one-sentence ideas, not elaborate narratives. They live in the front's back (`front.<key>-prep`), where every prep session finds them automatically and no play beat ever does.

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
