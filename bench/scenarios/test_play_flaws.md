# Test-play: finding the flaws prep cannot see

Exercises #191: `lens test-play` reads prepared content the way `play` would,
plays it through, and reports typed findings. The material is the five defects
stand-in models found while building #189, which authoring care did not catch,
each in an encounter of its own so a finding can be checked against exactly one
known defect — plus the corrected plaza, which must come back clean of
contradiction and impossible findings.

| Object | Defect | Expected type |
|---|---|---|
| `encounter.cellar-standoff` | "the crates by the stair give half cover from the door" reads two ways | `ambiguous` |
| `encounter.plaza-chase` | a 30-ft square carrying an escape that needs 60 ft of separation inside it | `impossible` |
| `encounter.rooftop-run` | a quarry with bonus-action Dash escapes on her first turn; the six-round clock never matters | `decided` |
| `encounter.bell-chase` | the bell rings at round 4 in a chase that ends by round 3 | `impossible` (dead trigger) |
| `encounter.quarry-ledge` | a 15-ft fall at 2d6, against `rules.hazards`' 1d6 per full 10 ft | `rules-error` |
| `encounter.plaza-chase-fixed` | none: the corrected reference | no `contradiction` or `impossible` |

```config
datasets:
  - rpg
  - lens-dnd
include_testing: false
```

The objects are written in D&D 5e terms (Dash, bonus actions, AC, cover), so the
reviewer needs that system in front of it: with `rpg` alone, `rules.system` is
the bundled Lasers & Feelings stub, and an honest reviewer flags every object as
a rules error against it, drowning the planted defects. `include_testing: false`
keeps `rules.skirmish` off play's module menu. The falling rule the `fall_damage`
step is judged against is the project-local `rules.hazards`, tagged on the
encounter, so the expected answer does not depend on how `lens-dnd` phrases it.

**Prompt keys exercised:** `test_play.system`, `test_play.instruction`,
`test_play.circumstances_suffix`, `test_play.no_spine_suffix`; in the design
steps also `design.system`, `design.instruction`

## Setup

Two level-4 PCs pinned at the root (`pc.rowan` speed 30, `pc.senna` speed 25
with Cunning Action); `stat.cutpurse` (speed 30, bonus-action Dash) and
`stat.smuggler`; `rules.hazards` (falling only); the six encounters above, each
tagged with its stat blocks so `<id>+` brings them; and an opening passage at
noon in Eight Fates. Nothing else is pinned: `test-play` pins each target itself.

**Implementation:** `bench/scenarios/test_play_flaws_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/test_play_flaws_setup.sh
```

To measure the assembled review context instead of running a model, pin the
target as an operator param (both `lens explain` and the run read
`params.test_play.targets`), then sweep the built project:

```bash
(cd "$PROJECT" && lens pin param set test_play targets encounter.quarry-ledge)
poe prompt-lab -- --project "$PROJECT" -o test_play
```

## Steps

### `ambiguous_cover`

Tests the **cold read**: the opening beat has to place the crates and say who
they cover against whom, and the finding has to quote the cover line.

```bash
lens test-play encounter.cellar-standoff -v
```

### `plaza_too_small`

Tests a **map that cannot host its own rule**: the reviewer measures the square
(about 42 ft corner to corner) against the escape's 60 ft.

```bash
lens test-play encounter.plaza-chase -v
```

### `dash_decides`

Tests **an outcome decided before play**: with initiative either way, the
cutpurse's Dash plus bonus-action Dash (90 ft) opens the 60-ft gap on her first
turn, and no PC can stop her moving that turn; the six-round watch clock never
fires.

```bash
lens test-play encounter.rooftop-run -v
```

### `dead_bell`

Tests **a dead trigger**: the scene rule ends the chase at the end of round 3,
so the round-4 bell can never ring.

```bash
lens test-play encounter.bell-chase -v
```

### `fall_damage`

Tests **a rules error against a pinned booklet**: `rules.hazards` arrives
through `encounter.quarry-ledge+`, and a 15-ft fall is one full 10 ft, so 1d6.

```bash
lens test-play encounter.quarry-ledge -v
```

### `reference_clean`

The corrected plaza. Tests that the reviewer does not manufacture defects: the
expected result is `No findings.`, and a `contradiction` or `impossible` finding
fails the step outright. Any `gap` or `ambiguous` finding must quote a real
line, survive a reread, and clear the bar — not a branch the GM rules on.

```bash
lens test-play encounter.plaza-chase-fixed -v
```

### `circumstances_override`

Planning ahead: the story says noon in a crowded town, the prompt says
otherwise. Tests that the cold read opens at night in an empty square (no crowd,
no lamps) and the playthroughs follow the stated approach, and that the
reviewer does not report the conflict with the story as a finding.

```bash
lens test-play encounter.plaza-chase-fixed --prompt "Two hours past midnight, the lamps out and the square empty of pilgrims. Senna tries to shoot the cutpurse before she reaches an alley."
```

### `no_spine`

Tests that `--no-spine` removes the story without inventing one, and that the
reviewer does not report a missing story as a gap.

```bash
lens test-play encounter.quarry-ledge --no-spine
```

### `design_loop`

Inside a design session: the draft is the session's proposals, the review lands
in a closed child, only the findings reach the session, and the next design
turn addresses them. Tests that `lens test-play` with no id finds the proposed
encounter, that the session node carries a `### Test-play findings: …` block,
led by the instruction to fix contradictions and cut or defer the rest, and no
playthrough text, and that the next `lens design` turn follows it: contradictions
fixed, everything else cut or left to the GM, and the encounter no longer than
before. One review is the loop; there is no second run to chase the count down.

```bash
lens design --module encounter "A pickpocket chase through the pilgrims' square on a market night: the cutpurse has Cunning Action, the party are Rowan and Senna."
lens test-play
lens design "Address the test-play findings."
lens design --end
```

## Evaluation criteria

Score each step on a 1–5 scale:

1. **Defect found** (flaw steps) — the known defect is reported, under the
   expected type, quoting the line it is about
2. **Typed right** — every finding's type fits its definition; a dead trigger is
   `impossible`, not `gap`; a rules disagreement names the booklet it disagrees with
3. **No invention** (all steps, `reference_clean` above all) — no finding that a
   reread of the object does not support; no matters of taste; no story proposals
4. **Cold read useful** — the opening beat states positions, distances, light,
   cover and stakes from the text alone, and names a choice where the text
   leaves one instead of making it silently
5. **Playthroughs real** — one or two approaches, aimed at the line most likely
   to break, each followed round by round with the PCs' and creatures' actual
   speeds and actions, to a stated resolution
6. **Bar held** — at most five findings, worst first, each one something two
   reasonable GMs would rule oppositely with a different winner or cost
7. **Mechanism only** — never rewrites the object, never proposes new fiction
8. **Loop mechanics** (`design_loop`) — proposals tested as proposed, review in
   a closed child, findings only on the session node, next design turn fixes
   contradictions and cuts or defers the rest instead of adding a rule per
   finding

## Prompt iteration guidance

**Focus key:** `test_play.system` (the two jobs and the finding types),
`test_play.instruction` (the output format the findings extraction relies on).

**Goal:** every known defect found under its type, and a clean reference that
stays clean. The second matters as much as the first: a reviewer that always
finds something trains the author to stop reading it.

**Anti-patterns:**

- **Taste as finding** — "the stakes could be higher", "consider adding a twist"
- **Rewriting** — a finding that supplies the replacement text instead of
  stating the defect
- **Unquoted findings** — a finding whose quoted line does not appear in the object
- **Generic playthroughs** — "the party fights and wins" with no rounds, speeds
  or distances
- **Gap inflation** — reporting every detail a GM would naturally improvise
  (the weather, a stall-keeper's name) as a `gap`
- **Branch coverage as finding** — "what does the hyena do if the party
  retreats", "nothing about resting on the stair": a GM rules on these in a
  sentence, and a reviewer that reports them turns prep into a flowchart
- **Dataset lint** — a finding about a stat block or rules booklet itself
  rather than the object under test
- **Story leak** — treating the story's noon against a `--prompt` midnight as a
  contradiction
