# Ground: a ravine mapped in the terms its rules decide by

Exercises #189: the ground a physical encounter is played on, written as a
`Ground` in the encounter, with distances placed against the speeds and ranges
in play, and play holding to it. The case is the eight-fates ravine, whose
original freehand prep contradicted itself three times — a floor "20–40 ft
wide" next to a den "200 ft across" from the stair, three switchbacks gaining
~10 ft over 300 ft of ravine, and nothing saying why the floor can't be walked
to the gate — and whose play drifted on light and distance from beat to beat.

- **Play** establishes the scene from `Ground`, keeps its zones and values,
  makes sure the player knows every distance, light level, cover and terrain
  feature with a mechanical consequence, and notes anything it adds in an
  `<!-- ai: -->` comment so later beats reuse it.
- **Design** (`design.encounter`) writes a `Ground` whose zones agree with each
  other, with distances chosen against the speeds and ranges in play. Ground
  is the place, not the scene: no positions in it, and what only this scene
  brings is a scene rule naming zones, so it holds whenever and from wherever
  the party arrives. Initial positions only when the scene opens at a known
  moment.

```config
datasets:
  - rpg
  - lens-dnd
include_testing: false
```

`include_testing: false` keeps `rules.skirmish` off the module menu (see
`play_dnd_rules_split.md`); this scenario supplies its own cast.

**Prompt keys exercised:** `play.system`, `play.instruction_continue`,
`design.system`, `design.instruction`

## Setup

Two level-4 PCs; `location.eight-fates` and its child `location.fates-ravine`
(ordinary location prose); and `encounter.ravine-approach`, tagged with the
ravine, carrying the reference `Ground` (six zones) and one ground change (the
gnolls' rope) as a scene rule naming zones. It gives no initial positions: the
Situation and the first beat place everyone. The root pins both PCs
and `encounter.ravine-approach+`, so `rules.encounter` (the encounter's
companion) is in the play context with no module request.

**Implementation:** `bench/scenarios/ground_ravine_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/ground_ravine_setup.sh
```

To measure the assembled context instead of running a model:

```bash
poe prompt-lab -- --scenario bench/scenarios/ground_ravine.md -o play
poe prompt-lab -- --scenario bench/scenarios/ground_ravine.md -o design -m encounter   # needs poe mock-llm
```

## Steps

### `set_the_scene`

The first beat. Tests that play **establishes from `Ground`**: the zones it
names, their heights, light and the Den's distance from the Rim are the ones
written, stated plainly, with flavour on top. With no initial positions given,
it places the party at the cairn and the gnolls at the Den lip from the
Situation, in Ground's zones. Nothing on the Rim is a freehand distance.

```bash
lens play "We stand at the cairn and look down the ravine. What can we see, and where are the gnolls?" --pass
```

### `descend_under_fire`

Movement across a crossing that has a check, under shots from a named band.
Tests that the climb is the one `Ground` gives (DC 10 Athletics, single file),
the Den is still 120 ft from the Ledge, and the hyenas trigger fires on
reaching the Switchbacks.

```bash
lens play "We take the stair down to the ledge, then Senna leads the climb to the switchbacks while Rowan covers her with the crossbow." --pass
```

### `ask_the_map`

Over-the-table talk. Tests that the answer gives the same distances, heights,
light and cover as `Ground`, not new ones, and that the game does not resume.

```bash
lens play "> [Player] Quick check: from the switchbacks, how far to the den, how high is it above us, and is it dim down here yet?" --pass
```

### `light_turns`

Time moves past mid-afternoon. Tests that the Ledge goes dim as `Ground` says,
and that anything play has to add (say, where the Sump is relative to the
Switchbacks) is stated in the same terms and noted in an `<!-- ai: -->`
comment.

```bash
lens play "We wait in the boulders until the sun is off the east wall, then work along the floor toward the gate." --pass
```

### `ground_gorge_invented`

Design invents a ground from nothing. Closes play and unpins the reference
encounter first, so no prepared `Ground` is in scope to copy. Tests that the
zones fit together (a width, a height and a distance across the same gap
agree), that distances sit where the speeds and ranges in play make them bite,
and that every way in or out is stated or ruled out.

```bash
lens play --end
lens pin kb remove encounter.ravine-approach+ /
lens design --module encounter "A gnoll ambush in a different gorge on the moor road: the party has to get down one wall, across the water and up the other while gnolls shoot from above."
lens design --end
```

### `ground_building`

A multi-floor building. Tests that floors, stairs and windows become zones
with height steps and crossings, not freehand measurements.

```bash
lens design --module encounter "A night break-in at the temple's tower in Eight Fates: three floors and a bell loft, where the token-sellers keep their ledger, with two acolytes on watch."
lens design --end
```

### `ground_plaza`

An open plaza. Tests that the zones that matter get distances between them
without a route to follow, that light changes with lamps and crowd, that
cover comes from stalls rather than walls, and that the chase runs on the
same distances: Ground's crossings are its complications, and the gap is read
against the same speeds (a move, a Dash) Ground was built on.

```bash
lens design --module encounter "A pickpocket chase through the pilgrims' square in Eight Fates on a market night."
lens design --end
```

## Evaluation criteria

Score each step on a 1–5 scale:

1. **Ground held** (play steps) — every distance, height, light level and
   crossing play states matches the encounter's `Ground`; no new number where
   `Ground` has one
2. **Gaps filled in kind** (play steps) — anything added uses the same kind of
   values and is noted in an `<!-- ai: -->` comment
3. **Mechanics stated plainly** (play steps) — the player is told every
   distance, light level, cover and terrain feature with a mechanical
   consequence, with flavour on top, not buried in it
4. **Distances that bite** (design steps) — 5-ft steps, placed against the
   speeds and ranges of the participants (just inside or past a move, a bow's
   normal range)
5. **Consistency** (design steps) — the zones agree with each other: widths,
   heights and distances across the same gap fit together, and every
   neighbouring zone says how you cross or why you can't
6. **The place, not the scene** (design steps) — Ground names no one's
   position and nothing only this scene brings; those are scene rules naming
   zones. Initial positions appear only when the scene opens at a known moment
7. **Scope** — a handful of zones, one line each, in the encounter; no new
   `location.*` objects for them

## Prompt iteration guidance

**Focus key:** the KB objects, not the prompt pack — SPATIAL AWARENESS in
`lens-dnd` `rules.encounter` for play; `design.encounter` and
`encounter._template` (both datasets) for design.

**Goal:** play reads `Ground` as the shared starting picture and never
re-measures it; design places distances where they change a decision instead of measuring
arbitrary space.

**Anti-patterns:** restating `Ground` with new numbers ("about 150 ft");
a distance nobody chose ("7 ft", "about 40 ft"); positions or scene props
written into `Ground`; a chase that tracks its gap on a different scale
from the `Ground` it runs across;
reciting `Ground` wholesale instead of telling the player what matters now;
zones that disagree with each other; a `location.*` built just to hold ground.
