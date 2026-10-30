# Ground: a ravine mapped to the ruleset's thresholds

Exercises #189: scene-scale space written as a `Ground` section on a
`location.*`, in the ruleset's own decision boundaries, and play holding to it.
The case is the eight-fates ravine, whose original freehand prep contradicted
itself three times — a floor "20–40 ft wide" next to a den "200 ft across" from
the stair, three switchbacks gaining ~10 ft over 300 ft of ravine, and nothing
saying why the floor can't be walked to the gate — and whose play drifted on
light and distance from beat to beat. Every one of those numbers was precision
no rule consumes.

Two sides are under test, and they share one vocabulary (SPATIAL AWARENESS in
`lens-dnd` `rules.encounter`):

- **Play** establishes the scene from `Ground` verbatim, states the bones
  openly, invents only what is missing in the same terms, and notes it in an
  `<!-- ai: -->` comment so later beats reuse it.
- **Design** (`design.location`) writes `Ground` only for scene-scale places,
  places things *at* thresholds, never states a sum along a route, and declines
  `Ground` for a settlement.

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

Two level-4 PCs; `location.eight-fates` (a settlement, no `Ground`);
`location.fates-ravine` with a reference `Ground` (six zones, threshold values
only); and `encounter.ravine-approach`, tagged with the ravine, whose positions
are zone plus band and whose one ground change (the rope) is a scene rule
naming zones. The root pins both PCs and `encounter.ravine-approach+`, so the
ravine's `Ground` and `rules.encounter` (the encounter's companion) are both in
the play context with no module request.

**Implementation:** `bench/scenarios/ground_ravine_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/ground_ravine_setup.sh
```

To measure the assembled context instead of running a model:

```bash
poe prompt-lab -- --scenario bench/scenarios/ground_ravine.md -o play
poe prompt-lab -- --scenario bench/scenarios/ground_ravine.md -o design -m location   # needs poe mock-llm
```

## Steps

### `set_the_scene`

The first beat. Tests that play **establishes from `Ground`**: the zones it
names, their heights, light and the Den's band from the Ledge are the ones
written, stated plainly, with flavour on top. Nothing on the Rim is a freehand
distance.

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

Over-the-table talk. Tests that the answer is in the vocabulary: bands, height
steps, light, cover — the same values as `Ground`, not new ones — and that the
game does not resume.

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

### `reprep_ravine`

Closes play, resets the ravine to the original freehand prep (the three
contradictions included), and asks `design.location` to re-prep it. The
reference `Ground` from Setup is the comparison.

```bash
lens play --end
lens kb add location.fates-ravine "$(cat <<'EOF'
The Ravine of Eight Fates

A sheer gorge below the town, running north to the Gate. The floor is 20–40 ft
wide, shingle and fast water. A narrow stair is cut into the east wall partway
down; from the stair the gnoll den is 200 ft across, a cave mouth on the west
wall. Below the stair, three switchbacks gain about 10 ft over 300 ft of ravine.
The Gate is an iron-bound door at the north end, above the water.
EOF
)"
lens commit
lens design --module location "Re-prep the ravine with Ground. The encounter there is a gnoll ambush on the descent, so it has to hold up in a fight."
lens design --end
```

### `ground_building`

A multi-floor building. Tests that height and stairs are steps the ruleset
knows, and that floors are zones rather than child objects.

```bash
lens design --module location "The temple's tower at Eight Fates: three floors and a bell loft, where the token-sellers keep their ledger. The party may have to break in at night."
lens design --end
```

### `ground_plaza`

An open plaza. Tests sightlines as bands between the zones that matter, light
that changes with lamps and crowd, and cover from stalls rather than walls.

```bash
lens design --module location "The pilgrims' square in Eight Fates on a market night — a pickpocket chase could start here."
lens design --end
```

### `ground_declined_settlement`

A settlement. Tests that the module **declines** `Ground` and builds the place
through the location hierarchy instead.

```bash
lens design --module location "Lowford, the village at the foot of the moor road where pilgrims stop before Eight Fates."
lens design --end
```

## Evaluation criteria

Score each step on a 1–5 scale:

1. **Ground held** (play steps) — every distance, height, light level and
   crossing play states matches `location.fates-ravine` `Ground`; no freehand
   number appears where `Ground` has one
2. **Gaps filled in kind** (play steps) — anything added is a threshold value
   in the same vocabulary, and is noted in an `<!-- ai: -->` comment
3. **Bones stated plainly** (play steps) — the spatial facts a player would
   draw on a grid are stated outright, with flavour on top, not buried in it
4. **Thresholds only** (design steps) — every spatial number in a `Ground` is
   one the ruleset distinguishes (5 ft; 30/60/90/120 ft; beyond; 10-ft height
   steps; bright/dim/darkness; difficult/climb/swim with a DC; cover grades)
5. **No contradictions expressible** (`reprep_ravine`) — the Den sits at a band
   from named zones, the Switchbacks are a climb with a height step, the Floor
   to Gate gap says why; no width, no route length, no sum along a route
6. **Scope** — 3–7 zones, one line each; sub-places are lines, not objects;
   `ground_declined_settlement` writes no `Ground`

## Prompt iteration guidance

**Focus key:** the KB objects, not the prompt pack — SPATIAL AWARENESS in
`lens-dnd` `rules.encounter` for play, `design.location` and
`location._template` for design.

**Goal:** play reads `Ground` as the shared starting picture and never
re-measures it; design places things at thresholds instead of measuring
arbitrary space.

**Anti-patterns:** restating `Ground` with new numbers ("about 150 ft");
inventing a width or a route length; a `Ground` on a village; a child
`location.*` for every zone; vocabulary copied into `design.location` that
drifts from `rules.encounter`.
