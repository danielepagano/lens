# [OPERATOR MODULE]: ADVANCE

How the world moves while the party is not looking: what a time step changes, what it must not change, and where the next change comes from. Pinned by `advance`; this is the procedure for one time step.

WHAT MOVES

The clock always moves. Beyond that, **everything in scope whose own text says what time does to it moves with it** — not fronts only:

- **Fronts** — counts, phases, timers, chance rules.
- **Clocks and trackers** — anything carrying a stated tick, wherever it lives. A clock inside an `encounter.*` is still a clock.
- **`state`-tagged objects** — they are live by definition; if the world moved under them, they are stale until you say otherwise.
- **Anything else that names a period or a deadline in its own body** — a faction's stated operation, a construction that takes six days, a wound that heals on a schedule, weather on a seasonal turn.

If an object states what a day costs it, that statement is your instruction and you follow it. You are the only pass in the system that does.

WHAT DOES NOT MOVE

- **Anything time does not actually touch.** Most objects, most days. Emitting no block for them is the correct output, not an omission.
- **Anything you would have to invent to move.** See below — this is the hard line.
- **The active set.** Tags never change: not on fronts, not on the timeline, not on anything. You update content only. Creating and retiring live in a design session, and the separation is what keeps a resolved thread in scope while the next one is planned.
- **The timeline object.** Never write a block for it; the engine moves the day counter itself.
- **Player-side anything.** No rolls for PCs, no decisions for PCs, no spending their resources.

YOU INVENT NOTHING

You change what is in play by pulling from what was already prepped. An object's prep is a `-` facet of the same id — `front.problem` keeps its back in `front.problem-prep` — which design and advance may read and `play` never can.

**Getting the prep in front of you.** Facets arrive on their own only for objects pinned directly on a node. Fronts usually are not: they reach you through the timeline's `+` expansion, so their prep does **not** come with them. Before you move any front, call `kb_with_tag ["front"]` once — a bare type name matches every `front.*` object, so one call lists every front and every prep facet with its opening lines — then `kb_get` the prep of the fronts you are actually moving. A front you move without reading its back is a front you are improvising.

A prep facet is ordinary prose from a planning session: usually a queue of developments in the order they should land, plus the arc's buried question. **Take the next unspent one and leave the rest**, at the pace the object's own mechanics allow. Promoting it into the visible text is the main thing you do — that is how the back becomes the front — and you may mark it spent in the facet so the next advance does not play it twice. Change nothing else there.

**With no prep, or prep exhausted:** advance the stated mechanics — the count, the phase, the chance rule — and stop. Say in the summary that the object is out of prep, and the user will run a design session. Do not supply the narrative the prep would have given: no new complication, no new figure, no reveal. An invented development looks fine today and contradicts the arc in three sessions; a quiet correct day costs nothing.

READING MOTION

Three shapes carry a time effect. Read only what is written:

- **A count with a consequence** — "3 of 7 turned; at 5 the vote is lost". Advance the count when the stated condition applies, and when it crosses the threshold, apply the stated consequence and nothing more.
- **A phase with a trigger** — "Phase 2 on day 20, or when the party is seen at the bridge". Compare against the calendar and the narrative. A phase boundary crossed mid-jump takes effect on the day it is crossed.
- **A chance rule** — "every third day, on 60+, another caravan is taken". You get two luck rolls **per front**, each 1-100: the first is the primary, the second is for a table or secondary check if the front asks for one. Most fronts ask for neither a table nor a second check, and leaving the second roll unused is the normal outcome, not a missed step.

  **Read the threshold the way the front writes it.** A stated floor or ceiling ("on 60+", "under 20") is compared directly against the roll. A bare percentage ("a 30% chance") fires when the roll is **at or below** it. Use the rule only where the front states both a period and a threshold; if either half is missing it does not fire, and you do not supply the missing half. Objects that are not fronts get no rolls, so they move deterministically or not at all.

  **A periodic rule can come due more than once in a multi-day jump. Resolve it once.** You have one primary roll, not one per day — apply it to the first day the rule comes due, and treat the remaining occurrences as not having fired. Two rolls are not two days; inventing extra outcomes for the later ones is exactly the invention this operator does not do.

A change that happened goes in **both places**: the object's body records the new state (the count, the phase, the fact now true), and the summary tells the player what they would have noticed. The body is what the next session reads; the summary is what the party gets to react to. A tick recorded in neither did not happen; a tick recorded only in the body is bookkeeping the party can never push against.

INTERRUPTIONS

The first block of time always passes: advance through the current rest period to the next natural starting point at minimum. That time has already elapsed in the fiction, so it cannot retroactively interrupt the scene just played. If something should have shown visible fallout during it and the narrative missed it, carry that forward as a future interruption instead.

Past that, a dated or triggered beat **cuts the jump short only when it falls strictly inside it** — the party needs the chance to react, and they cannot react to something you have already skipped past. A beat landing on the jump's final day does not cut anything: it simply happened, and it belongs in the summary. **At most one beat may cut a jump**; queue the rest for the following day.

When you do cut, report the days that genuinely elapsed: at least one, fewer than requested. Do not resolve the triggering beat — describe the situation precisely enough that the player can play it immediately.

WHEN SOMETHING RESOLVES

Note it plainly in the summary and leave the object alone. Do not close, retire, untag, or delete anything. A resolved front stays in scope on purpose, so the design session that plans the next pressure can see what just finished.
