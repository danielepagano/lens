# Play: held-back parts and trigger offers

Exercises triggers (#195). Prep for the edge of the Thornwood
(`prep.thornwood_edge`) declares two parts it deliberately did not write, as
triggers in its front matter:

- `design-first-stones` — **a place nobody has designed yet.** The first ring of
  standing stones may never be reached, and when it is it should be built
  against the state the scene is in. This is the trigger the scenario fires.
- `design-warden-fight` — **an escalation that needs combat prep.** It must stay
  quiet throughout, since nothing here turns violent. It is the distractor.

Both are moments a GM would genuinely pause for: walking into a site that has not
been built, or a standoff turning into a fight. That is the point. A trigger on
something casual, like lifting a stone, asks the model to stop mid-gesture,
which no GM would do, so a model that narrates past it is arguably right.

`play` sees both in a tail `[HELD BACK]` block and has to **recognise the
moment**, narrate up to the threshold, stop, and emit `<!-- suggest:<slug> -->`.
Then the offered `design` session, opened by the trigger, builds the place and
declares and suggests the follow-up `play-…` trigger.

The failure this exists to catch: the model walks Elena into the ring, **invents
what is there**, and emits the marker anyway.

Uses **`pc.elena`**, **`location.thornwood`** and **`npc.thornwood_warden`**
from the `testing` dataset. The warden's secret is that he reports anyone who
gets past the first standing stones.

```config
datasets:
  - rpg
```

**Prompt keys exercised:** `play.held_back`, `shared.block.held_back`,
`play.instruction_continue`, `design.system` (HOLD PARTS BACK),
`design.trigger_opened`, plus the `kb_set_trigger` / `suggest_trigger` tool
descriptions.

## Setup

Writes `prep.thornwood_edge` with both triggers, pins it with the cast on the
root node, and seeds the opening passage (same scene as `play_gm_voice`).

**Implementation:** `bench/scenarios/play_held_back_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/play_held_back_setup.sh
```

## Steps

### `approach`

A conversation with the warden at the marker stone. Neither moment has happened.
Tests **restraint**: no `<!-- suggest:… -->` marker, and nothing about the
stones described as established fact beyond what prep says.

```bash
lens play "I greet the warden and ask where the deer path goes." --pass
```

### `enter_the_ring`

Elena walks the path to the stones and steps in. Tests **recognition and the
stop**:
- the reply narrates the walk and the arrival, up to the threshold, and ends
  with `<!-- suggest:design-first-stones -->` on its own line;
- it does not describe what is inside the ring or what happens there;
- `design-warden-fight` is not suggested.

```bash
lens play "I thank him, take the deer path east past him, and keep walking until I reach the first standing stones. I step into the ring." --pass
```

### `build_the_ring`

Fires the offer. Off a terminal the CLI prints a hint instead of asking, so the
bench runs it explicitly. The design session opens as `design-first-stones-tr`
with the trigger and its `when` in its task. Tests that design **builds for the
moment the player stands in**: what Elena meets inside the ring right now,
consistent with the warden's watch. It should then declare `play-first-stones`
on `prep.thornwood_edge` (the default, so no `id` is needed), with a `run` that
pins what it built, and call `suggest_trigger` for it.

```bash
lens trigger design-first-stones
```

### `end_design`

Closes the design session. Tests the close:
- the KB is written;
- the parent play session gets `<!-- suggest:play-first-stones -->` after the
  close tag;
- the CLI prints the offer;
- `lens stats` lists it under the cursor.

```bash
lens design --end
lens stats
```

## Evaluation criteria

Score each step's output on a 1–5 scale:

1. **Restraint** — `approach` has no marker and does not establish what is at
   the stones
2. **Recognition** — `enter_the_ring` emits exactly
   `<!-- suggest:design-first-stones -->`, on its own line, at the end, and
   never `design-warden-fight`
3. **Stop at the threshold** — `enter_the_ring` describes the walk and the ring
   as seen from its edge at most, and nothing of what is inside or what happens
   there. The beat ends as Elena steps in.
4. **Built for the moment** — `build_the_ring` writes a place for that moment
   (Elena inside the ring, the warden's watch already in motion), not generic
   location prep
5. **Follow-up declared and offered** — `build_the_ring` calls `kb_set_trigger`
   for a `play-…` slug whose `run` pins the new content, and `suggest_trigger`
   for it. `end_design` lands the marker after `[/design:design-first-stones-tr]: #`.
6. **No leakage of the machinery** — no `run` command, flag or slug list appears
   in play prose, and the held-back block's instructions are never echoed

## Prompt iteration guidance

**Focus key:** `play.held_back`. If the model describes the inside of the ring
before stopping, the threshold sentence is too weak. If it suggests on
`approach`, or suggests the fight, the "never emit one for a moment that has not
happened" clause is.

**Goal:** the marker appears exactly when the `when` line has just happened in
the fiction: not when it becomes possible, and not one beat late.

**Anti-patterns:**
- suggesting every held-back part "just in case";
- narrating the place and then suggesting it;
- restating the `when` text verbatim as prose;
- on the design side, building generic location prep instead of the moment, or
  suggesting from a session that was not opened by a trigger.
