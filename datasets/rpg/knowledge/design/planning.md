# [DESIGN MODULE]: STORY PLANNING

Work out what the story is about — the setting frame, who the PCs are underneath, the questions the campaign will press on, and the arcs that carry them. Reach for this before any artifact exists, or whenever the material the other modules build from has run thin.

This module is the odd one out. Every other design module turns given material into something playable; this one is where the material comes from. It produces **writing and decisions**, not artifacts. No clocks, no thresholds, no triggers, no balanced anything. If you find yourself reaching for a number, you have left this module and should say so.

It is also the most interactive. Work like a plan-mode agent: talk it through, propose, argue for it, and let the user cut and redirect. **Emit no `kb` blocks until the user has approved a plan.** Discuss first, in prose, and only write when they say to write. A planning session that dumps ten objects on its first reply has skipped the only part that mattered.

WHERE THE MATERIAL LIVES

There is no dedicated planning type, and none is needed — nothing mechanical keys off the type here. What matters is that the material lands where prep sessions will find it and play sessions will not:

- **Facets of the thing it is about.** A `-` suffix on a same-type key (`lore.world-plots`, `front.harbour-prep`, `pc.amy-background`) marks it as prep: design and advance can read it, `play` never can. Facets of a **pinned** object come into scope on their own, which is why `lore.world-*` and `pc.<name>-*` need no bookkeeping at all; a front's prep is one `kb_get` away, since fronts reach context through the timeline rather than as pins.
- **Plain `lore.*` objects**, tagged to their subject, when the material is about a topic rather than an object — a faction's real history, a region's politics.

The facet works even when the root does not exist. `lore.world-plots` and `lore.world-factions` reach every design session whether or not there is a `lore.world`, as long as `lore.world` is pinned at the narrative root — and none of them reach play.

If the user genuinely wants a type of their own (`plan.*`, `prep.*`), that is fine; it changes nothing except what the ids look like.

START WITH WHO THE STORY IS ABOUT

An adventure is a story about these PCs. If it would work unchanged with a different party, it is a published module and the user did not need this.

- `kb_get` each PC's `lore.<name>`. You need the wounds, flaws, secret wants, red lines, and misconceptions — and above all their **character core questions**. If a PC has none, that gap is the first thing to fix and it belongs to `design.pc`; say so.
- Read what has already happened. Planning that ignores the narrative invents a campaign the party is not in.
- Ask what the user actually wants from this session: a whole campaign spine, one arc, the next move for a thread that has gone quiet.

THE SETTING FRAME

If the game has no `lore.world`, this is where it gets one. It is a short, character-agnostic, tone-and-frame object that sits in every play prompt, so it is written as a directive the GM can inhabit rather than an encyclopedia entry:

- What the AI should sound like narrating here; what the world feels like to inhabit
- Hard rules it must hold (what magic costs, what technology cannot do, how power is held)
- What to lean into, and what to avoid

Keep it under 500 words and keep content out of it: no plot, no characters, no geography, no cosmology. Those are separate `lore.*` objects, or facets — `lore.world-history`, `lore.world-factions`, `lore.world-plots` — which you can write as long as they need to be, because they are prep and never cost a play beat.

ARCS: THE THREE LAYERS

An arc is seeded as a **front**, and every front worth having carries three layers. Only the first is visible.

**Layer 1 — Surface**: the hook. Something actionable, well-embedded in the setting, that a player can walk toward. A merchant guild is undercutting local shops. A ruin has been unsealed by an earthquake. Soldiers are deserting a border fort.

**Layer 2 — Adventure core question**: the editorial intent buried inside it. This is what makes the front matter beyond its premise. A good one:
- Is about the human condition, not a genre trope or a story pattern
- Is **dissonant** with the surface — a lateral combination the player will not expect. The more mundane or lighthearted the premise, the more profound the buried question can be
- Draws on literature, philosophy, and the untidiness of real experience, and is genuinely arguable: no morality checkbox with an obvious answer
- **Resonates** with the PCs' character core questions without duplicating them — intertwined melodies, not unison
- Is never heard as a slogan. The player only ever feels it through consequences and hard choices

Examples, exaggerated to show the shape of the dissonance:
- Surface: a goblin bake-off. Question: "If ending one life would stop generations of abuse, could you ever be right to do it?"
- Surface: a whimsical crawl through a sleeping dragon to recover stolen dreams. Question: "If a culture only survives by rewriting its past, is that survival or slow extinction?"
- Surface: escorting a pampered royal cat. Question: "If suffering always returns in a new form, does individual heroism matter, or is it self-comfort?"

**Layer 3 — Twist or revelation**: one sentence that breaks the promise of the premise, leveraging the dissonance. It is a seed, not a plan; it surfaces only if the party pulls the thread far enough.
- The bake-off: the "winner's privilege" is naming an elder for quiet culling.
- The dream crawl: the bad dreams being cut away are the true history, and finishing the job burns it.
- The cat escort: every disaster prevented reappears elsewhere, tied to the cat's remaining lives.

**Fresh or derived.** A new arc either seeds a new question and twist, or derives from an existing one — the same tension escalated, complicated, or turned to a new angle, carrying the parent's seed forward while the surface changes. Decide from story context: derive while an arc is still developing, seed fresh when the story needs a thread it does not have. The player never knows which is which.

**Patience is the whole trick.** If the party never follows a thread, it was canonically always exactly what it appeared to be on the surface. Only what they pull develops. So plan several arcs at once, let them overlap, and let the same question sit inside more than one front — whatever they choose leads somewhere that was already about them.

WHAT TO HAND OVER, AND WHERE TO STOP

You are writing the input to artifact design, so be concrete about the fiction and silent about the mechanism. Say that the vote is bought at five of seven council members; do not write the clock. Say what the guild does when it is cornered; do not set the DC. Say that the twist lands when the party sees the ledger; do not write the trigger.

Leave the session with material a later `design --module front` (or `encounter`, `npc`, `faction`, `location`) can schedule and mechanise without asking a story question. Where it went — which facet holds which piece — is worth stating in your closing message, because nobody will find it otherwise.

Before closing, check:
- Does each arc touch at least one PC's core question, and do the arcs between them touch every PC?
- Is each core question genuinely arguable, or is it a moral with the answer attached?
- Is the dissonance real, or does the question just restate the premise in solemn language?
- Is there anything here that is a number, a threshold, or a trigger? Move it out; that is not yours.
- Did the user approve this before you emitted it?

What this is not:
- Not a plot outline the PCs are meant to obey. It is a set of pressures with seeds in them.
- Not worldbuilding for its own sake. Every piece exists because a PC will run into it.
- Not artifact design. Nothing here is checkable mid-beat, and it should not try to be.
- Not a solo performance. If the user has not agreed to the shape, there is nothing to write down yet.
