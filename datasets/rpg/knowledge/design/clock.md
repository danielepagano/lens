# [DESIGN MODULE]: CLOCK

Build a **clock**: a named countdown with a stated number of segments, a stated trigger for filling one, and one concrete thing that happens when it fills. Pull this module in alongside encounter or front design whenever a scene has something arriving on its own schedule.

A clock is not a KB type. There is no `clock.the-alarm` object. A clock is a four-line artifact you write **inside** another object — usually an `encounter.*` or a `front.*` — and its whole value is that it turns "there is time pressure here" into something the GM can point at, tick, and be held to.

THE ARTIFACT

Write it exactly in this shape. Four lines, no prose around them:

```
Clock: Alarm [4]
- Ticks when: the party is seen, a body is found, or a patrol misses a check-in (+1 each); a fight is heard anywhere in the wing (+2)
- At full: the wing seals and six guards converge on the last known position — not "they are discovered"
- Starts: 1 (the gate guard already noticed the wagon)
```

- **Name and size.** The name is what is *coming*, in two or three words. The size is 4, 6, or 8 — see SIZING below. Write it as `[4]`, not "four segments".
- **Ticks when.** The events that fill it, with how much each one is worth. This is the load-bearing line: if you cannot list the triggers, you do not have a clock, you have a mood.
- **At full.** ONE concrete event, stated in the fiction. Not a state ("they are alerted"), not a difficulty adjustment ("things get harder") — a thing that happens, with actors and a place.
- **Starts.** Only when it starts partly filled, which is often the honest state of a scene already in motion. Omit the line otherwise.

SIZING

Segment count is a statement about how much work the thing takes, not about how tense you want the scene to feel.

- **4** — a complex obstacle; a few beats. A guard patrol closing in, a lock with a real mechanism, a crowd turning.
- **6** — a complicated obstacle; most of a scene. A negotiation collapsing, a fire spreading through a building, a ritual reaching its verse.
- **8** — a daunting obstacle; a whole scene or a long-term project. A siege breaking, a plague crossing a province, a device being built from nothing.

If a thing needs more than 8, it is not one clock. Split it into linked clocks (below) so the party can see a phase end.

KINDS OF CLOCK

Pick the kind deliberately; each one carries different pressure.

- **Danger.** One clock, filled by the world. The default. Suspicion, pursuit, structural failure, the deadline.
- **Race.** Two clocks that advance against each other — the party's progress and the threat's. Say plainly which one fills first if both would fill on the same beat.
- **Linked.** One clock's completion starts the next. Use for staged jobs: `Gain Entrance [4]` filling starts `The Guards Arrive [6]`. This is how a long problem stays legible.
- **Tug-of-war.** One clock that both fills and empties as each side gets the edge. Say what empties it, or it is just a danger clock that occasionally forgives you.

WHERE IT LIVES

- **Inside an `encounter.*`** when it only matters for that scene. Put it in the scene rules with the rest of the procedure.
- **Inside a `front.*`** when it advances between scenes. Then the `Ticks when` line must be answerable by `advance` without a scene to read: "one segment per day the mine stays open", "a segment each time the party is seen using the relic". A front clock whose trigger only exists inside a scene will never move.
- **Never in its own object.** A clock is small and belongs to the thing it threatens. Two objects that both carry the same clock is a bug, not reuse.

Tag `rules.clock` on any object that carries a clock the GM has to run over multiple beats — that is what puts the running procedure in front of `play` at the same time as the clock itself. A single-tick clock in a one-scene encounter does not need it.

CHECKING YOUR WORK

A clock is not finished until every one of these is true:

- Can you name the events that tick it, without re-reading the scene? If not, the clock is decoration.
- Is `At full` one event with actors and a place, rather than a state of affairs?
- Would the party, watching it fill, have something to *do* about it? A clock nobody can affect is a timer — which is fine, but say so and stop pretending it is a clock.
- Does it fill in a plausible number of beats at the size you gave it? A 4 nobody can tick twice is a 2.
- Is it the only clock in the scene, or does each one track a genuinely different thing? Two clocks that always tick together are one clock.

WHAT THIS IS NOT

- Not a health bar for the scene. If ticks come only from combat damage, delete it.
- Not a hidden schedule. Default to a clock the player can see; hide one only when the not-knowing is the point, and note in the object that it is hidden.
- Not a way to make failure automatic. A clock that fills whatever the party does is a cutscene with extra steps.
- Not a place to re-explain how clocks work. `rules.clock` covers the procedure; the object carries only this clock's deltas.

<!-- Sources for the practice this module encodes: John Harper, *Blades in the Dark* — Progress Clocks (https://bladesinthedark.com/progress-clocks); Mike Shea, "Progress Clocks for Complex Situations in D&D" (https://slyflourish.com/progress_clocks_in_dnd.html); "How Progress Clocks Can Elevate TTRPGs" (https://www.domainofmanythings.com/blog/progress-clocks-for-ttrpgs). -->
