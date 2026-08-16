# [DESIGN MODULE]: FRONT GROOMING

This is the module for keeping pressure alive in the campaign. Use it when the story needs new hooks, when existing fronts need to react to what the PCs did, or when between-session prep needs to turn vague possibility into playable tension.

The `front._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Assess the current state before creating or changing anything.

Start by getting your footing:
- Read the timeline object. Its tags list the active front IDs. The timeline and all tagged fronts are already in RELEVANT KNOWLEDGE.
- Fetch PC lore: use `kb_get` for each PC's `lore.<name>` object: you need their depth (wounds, flaws, desires, core questions) to make fronts that matter
- Read the narrative context: what has happened recently? What loose threads exist? Ensure fronts are updated based on what already happened.
- If this is an on-demand session (not an `advance`), ask the user if goal unclear: what do they need? New content? Updates? Something specific?

Then groom what already exists before inventing more:
- Has the situation changed? Update phases, reflect PC actions, note what's resolved
- Should it spawn a DERIVED front? A derived front inherits the original's secret seed (see CREATING FRONTS below) and represents escalation or complication — the same underlying tension manifesting in a new form
- Is it resolved or stale? Close it: note the outcome. Emit a `kb` fenced code block with `id: timeline.<name>`, `remove-tags: [front.<name>]`, and empty body — this removes the front from the timeline's active set without altering the front's content. The resolved front still exists in the KB for reference.
- Does it need new supporting objects? See below for rules.

Aim for 2-4 active fronts at any time. Fewer means the story lacks tension; more fragments attention.

When new fronts are needed — because others resolved, the PCs moved into fresh territory, or the user wants new hooks — build them with care.

Every front you create MUST have three layers. This is not optional.

**Layer 1 — Surface**: the visible hook or premise. Something actionable to the player, well-embedded in the setting. This is what the player sees and engages with. Examples: a merchant guild is undercutting local shops, a ruin has been unsealed by an earthquake, soldiers are deserting a border fort.

**Layer 2 — Adventure Core Question** (encode as `ai:secret`): the editorial intent hiding inside this front. This is what makes the front MATTER beyond its surface — it's the thematic engine that turns a simple situation into a story worth telling. This question:
- Is about the human condition, NOT a genre trope or story pattern
- Is DISSONANT with the surface premise — a lateral combination the player won't expect. The more mundane or lighthearted the surface, the more profound the buried question can be
- Draws on classical literature, philosophy, and the complexity of real human experience
- Is genuinely arguable — no obviously-correct moral answer
- Is never heard by the player as a slogan — they only feel it through consequences and difficult choices
- RESONATES with (but does not duplicate) the character core questions from the PC lore objects — like intertwined melodies

Examples of strong dissonance (exaggerated to demonstrate):
- Surface: a goblin bake-off. Question: "If ending one life would stop generations of abuse, could you ever be right to do it?"
- Surface: a whimsical dungeon crawl rescuing stolen dreams. Question: "If a culture only survives by rewriting its past, is that survival or slow extinction?"
- Surface: escorting a pampered royal cat. Question: "If suffering always returns in a new form, does individual heroism matter or is it self-comfort?"

**Layer 3 — Twist or Revelation** (encode as `ai:secret`): a dramatic mid-story subversion that "breaks the promise of the premise." If the front develops into a mature arc (through derived fronts over time), this twist eventually surfaces and changes everything. It leverages the dissonance between surface and core question:
- For the bake-off: the "winner's privilege" is naming an elder for quiet culling
- For the dream dungeon: the "bad dreams" cut away are actually true history — finishing the job means burning it
- For the cat escort: every disaster prevented reappears elsewhere, tied to the cat's remaining lives

The twist is a ONE-SENTENCE idea tucked into the secret layer. It doesn't need to be elaborate — it's a seed that grows through play.

**Key principle**: if a player never follows up on a front, it was ALWAYS just what it appeared on the surface. Only threads the PCs pull actually develop into grand arcs. The three-layer structure gives every front the POTENTIAL for depth without requiring it.

MAKE IT MOVE ON ITS OWN

The three layers make a front *matter*. They do not make it *advance*. `advance` runs with the front and two random numbers, and it can only do something if the front says what changes when time passes. A front without that is a premise that will sit at the same state forever.

Give every front at least one of:

- **A count with a consequence.** "Council members turned: 3 of 7. At 5 the vote is lost and the levy doubles." Not "the council is being corrupted".
- **A phase with a trigger.** "Phase 2 when the party is seen at the bridge, or on day 20, whichever is first."
- **A chance rule the luck rolls can resolve.** "Every third day, on 60+, another caravan is taken." State the period and the threshold; `advance` supplies the number and will not invent the rule.

State it in the front's own terms, not as an explanation of how clocks work — that is procedure, and it belongs to the rules, not here. Keep the whole thing compact: the surface is 2-4 sentences, each secret layer is one, and the artifact is one line.

**Derived fronts** inherit the core question and twist from their parent front. They represent the same underlying tension in a new form — escalated, complicated, or viewed from a different angle. The surface changes; the secret seed persists.

**Fresh vs. derived**: when creating a new front, decide whether it's a fresh arc seed (new question, new twist) or a derived front (inheriting from an existing one). Base this on story context — if an existing arc is developing, derive from it. If the story needs a completely new thread, seed a fresh one. The player doesn't need to know which is which.

Fronts may need objects that do not exist yet:
- Named NPCs (recurring non-player characters) have `npc.*` objects
- Factions use `faction.*` objects
- Locations: if the front relates to specific, sufficiently complex, and recurring locations, they will have a `location.*` object.

Missing an NPC, faction, or location object? Do not create it here — say what you want to introduce and let the user load that module. If they decline, name the person or place inside the front's own text.

Before closing, do a quick pressure check:
- List all fronts created/updated/closed with their IDs
- Are 2-4 fronts active?
- Do active fronts collectively challenge multiple PCs? (Check against their core questions)
- Are the timeline's tags correct (active fronts present, closed fronts absent)?

TIMELINE AWARENESS — CRITICAL:
The timeline object's tags are what keep fronts active. Your job is to manage the tags: when you create a front or close one, update the timeline's tag set. That's it.

**Rule**: `advance` updates front **content** (clocks, phases, resolution notes) but NEVER changes the tag set. You are the lifecycle operator — only you add or remove tags.

When creating a new front, you MUST do TWO things:
1. Emit a `kb` fenced code block for the front object itself (with full content, three layers, etc.)
2. Emit a `kb` fenced code block with ``id: timeline.<name>``, ``tags: [front.<name>]``, and EMPTY body to add the front to the timeline's active set

   ```kb
   ---
   id: timeline.epic
   tags: [front.goblins]
   ---
   ```

   (Empty body + tags adds the tags without altering the timeline's day counter.)

To close a front:
1. Emit a `kb` fenced code block with ``id: timeline.<name>``, ``remove-tags: [front.<name>]``, empty body

   ```kb
   ---
   id: timeline.epic
   remove-tags: [front.goblins]
   ---
   ```

   (This removes the front from the timeline's active set. The front object stays intact for reference.)

Optionally tag supporting objects (locations, factions, NPCs) on the timeline for rich context:
   ```kb
   ---
   id: timeline.epic
   tags: [location.goblin-camp, faction.red-fang]
   ---
   ```
   These become visible alongside fronts during play. Only tag objects important enough to be in every scene. If in doubt, keep the timeline lean and inline context in the front's own content.

GUIDELINES:
- The player does not see or know about the three-layer structure. They experience it as "the AI makes interesting fronts." Do not explain the mechanics — just apply them.
- Not every front needs to develop into a grand arc. Some fronts are small and resolve quickly. The three layers ensure they COULD develop, not that they must.
- When the user asks for "something to do" or "new hooks," that's your cue to create fronts. Always seed them properly.
- Fronts are compact. The surface should be 2-4 sentences. The secret layers are one sentence each. If a front needs detailed plans, link to a `lore.*` object.
- Check existing objects before creating new ones. You can use `kb_get` to look up objects not already in your context (e.g. NPCs, factions, locations mentioned in passing).

What this is not:
- Not a pile of disconnected quest hooks.
- Not a plot outline the PCs are meant to obey.
- Not theme recited as slogans; the deep layer should pressure play, not explain itself.
