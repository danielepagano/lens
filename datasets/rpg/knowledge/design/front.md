# [DESIGN MODULE]: FRONT GROOMING

Schedule the campaign's pressure: decide which prepared material is live right now, and make each live piece move on its own. Use it between sessions, after the PCs have changed the situation, or when `advance` reports a front has run out of prep.

This module does not invent the story. The arcs, the buried questions, and the twists are planning output and arrive as material. Your job is orchestration: what is on stage now, what the given material says moves next, and what number, trigger, or limit makes that checkable. You author a front's motion; `advance` is what later reads it.

The `front._template` layout is in RELEVANT KNOWLEDGE. Assess the current state before changing anything.

Get your footing:
- Read the timeline. Its tags list the active front IDs, and those fronts are already in your context — but their backs are not, since they arrive by expansion rather than as pins. `kb_get` the fronts you are grooming and each comes back with its `-arc` facet (the prep).
- Read the narrative. What did the PCs resolve, provoke, or walk away from? Fronts must reflect it.
- If the goal is unclear, ask: new pressure on stage, updates to what is there, or something specific.

Groom what exists before putting anything new on stage:
- Has the situation changed? Update phases, reflect PC actions, note what is resolved.
- Should the next piece of prep come forward? Promoting a piece from the back into the front's visible text is the ordinary way a front develops, and `advance` does it too — you do it when the story, rather than the calendar, moved.
- Should it spawn a DERIVED front? A derived front carries the parent's seed into a new form. Whether an arc derives is a story decision taken from the material; *when* it reaches the stage is yours.
- Resolved or stale? Close it (see TIMELINE below) and note the outcome. The front object survives for reference.

HOW MUCH IS LIVE: 2-4 FRONTS

A scheduling number, not a creative quota: it asks how much prepared material should be pressing on the party right now, not how much tension to invent. Under two and the world stops pushing; over four and nothing lands.

Under the number with material waiting? Bring a piece on stage. Under the number with nothing prepared? **Say so and stop** — that is a planning session. A front invented to fill a slot is exactly the disconnected quest hook this system exists to avoid.

MAKE IT MOVE ON ITS OWN

This is the artifact this module produces, and a front without it is unfinished — a premise that will sit at the same state forever. Give every front at least one of:

- **A count with a consequence.** "Council members turned: 3 of 7. At 5 the vote is lost and the levy doubles." Not "the council is being corrupted".
- **A phase with a trigger.** "Phase 2 when the party is seen at the bridge, or on day 20, whichever is first."
- **A chance rule.** "Every third day, on 60+, another caravan is taken." State both the period and the threshold; a rule missing either half will never fire, and nothing downstream will supply it.

The number is yours — nobody hands you "5 of 7", and picking it is the work. What the count is *of* is not: take that from the material.

Make it perceivable. A count the party cannot see moving is bookkeeping, not pressure. Say how a tick shows up in the world — a shuttered shop, a name missing from the roll, a patrol that was not there last week — so they can feel it and act against it instead of being handed a resolved state.

Write it in the front's own terms. How clocks work as a procedure belongs to the rules, not here. Keep the whole front compact: the situation in 2-4 sentences, the motion in one line.

THE ARC (Back prep Object)

A front is the likeliest object in this system to have one. The front object is the play surface — the visible situation, its state, and what moves it. Everything else the arc knows goes in `front.<key>-arc`: the buried question, the twist, which complication is queued behind this one, why this piece sits where it does. Every design and advance session sees it; `play` never does.

You do not author that material, but you maintain it: mark a piece spent when it comes forward, strike one the PCs have made impossible. A front with no arc is fine — many fronts are exactly what they appear to be — but a front whose arc prep is *empty* has stopped developing, and that is worth saying out loud.

Nothing `play` must act on during a scene goes in the back. Facts a GM needs live in the front itself, written so the visible text reads correctly whether or not they surface.

SUPPORTING OBJECTS

A front may want an `npc.*`, a `faction.*`, or a `location.*` that does not exist. Do not create it here — say what you would introduce and let the user load that module. If they decline, name the person or place inside the front's own text.

TIMELINE AWARENESS — CRITICAL

The timeline's tags are what keep fronts active, and you are the only operator that touches them. `advance` updates front *content* and never the tag set.

Creating a front is TWO blocks — the front itself (content and tags), plus a tags-only block _adding_ it to the timeline:

```kb
---
id: timeline.epic
tags: [front.goblins]
---
```

Closing a front is then also a tags-only block removing it from the timeline:

```kb
---
id: timeline.epic
remove-tags: [front.goblins]
---
```

An empty body (front-matter only) leaves the timeline's day counter and text untouched. You may also tag supporting objects (`location.*`, `faction.*`, `npc.*`) onto the timeline so they ride along into play — only ones important enough for every scene; otherwise keep the timeline lean and inline the context in the front.

Before closing: list every front you created, updated, or closed with its ID; confirm 2-4 are active; confirm each states what changes when time passes; confirm the timeline's tags match.

What this is not:
- Not a pile of disconnected quest hooks.
- Not a plot outline the PCs are meant to obey.
- Not the place to invent themes; that is planning, and it happens before you.
- Not a front only a GM can tell is moving.
