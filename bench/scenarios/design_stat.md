# Design: custom stat blocks (`design.stat`)

Exercises the **`design.stat`** module in `lens-dnd`: building a `stat.*` block
for a creature the reference material does not have. The module's whole claim is
that custom creatures go wrong *before* the writing — in the target CR, in what
the block is for, and in whether real blocks were read first — so the three steps
below differ in exactly how much of that arrives with the brief.

What is under test:

- **Harvest discipline.** The dataset has 333 published blocks. A model that
  writes numbers without reading any of them at the target CR produces a block
  that does not sit next to them, and nothing downstream will catch it.
- **CR as the creature's own property.** The target CR is settleable on its own;
  what a situation contributes is the *mix* — how many, alongside what. A step
  with no situation at all should still be a complete brief.
- **Tag discipline.** `cr:` is read for XP by `balance_encounter`; a block
  without one silently prices at 0. Tags are a closed vocabulary in
  `stat._template`, and an invented one matches nothing.
- **Not restating the template.** `stat._template` owns the layout; the module
  owns the judgment. Output should be one fenced `kb` block, not a lecture.

```config
datasets:
  - rpg
  - lens-dnd
include_testing: false
```

**Prompt keys exercised:** `design.system`, `design.instruction`

## Setup

Four level-5 PCs with hit points on the sheet (the module's one-round check
needs the most fragile PC's HP to be knowable), a vault keeper with no stat
block, and a half-built encounter whose roster has a hole where its boss goes.
Nothing is pinned but the party — the encounter and the NPC arrive per step, the
way they would when a user points at them.

**Implementation:** `bench/scenarios/design_stat_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/design_stat_setup.sh
```

## Steps

### `stat_boss_from_npc`

The dense case: an existing `npc.*`, a pinned encounter that already names the
rest of the roster, and a party whose levels are on their objects. Everything the
module asks for in steps 1 and 2 is present, so the work is harvesting, the
one-round check against a 33-HP wizard, and arithmetic that holds together.

Watch for: does it read blocks at the target CR before writing; does it price the
roster; does the block deliver *Vasa* rather than a generic drowned spellcaster;
does the damage it can land on one PC in one round get checked out loud.

```bash
lens design --module stat --pin encounter.tidewater-vault --pin npc.vasa-thornwake "Vasa needs a stat block. She is what the party has to get past in the vault, and the rest of the roster is already in the encounter."
```

### `stat_drowned_attendants`

The mix case. Six of them fight alongside the boss, so the creature's own CR is
low and the *encounter's* weight comes from quantity. Tests whether the model
keeps those two apart, and whether it reaches for `stat.*` candidates it could
reskin (`stat.ghoul`, `stat.specter`, `stat.zombie` are all in the dataset)
before inventing from nothing.

```bash
lens design --module stat "The vault's drowned attendants — six of them work alongside Vasa. They should read as people who drowned in service and never stopped working."
```

### `stat_reached_from_encounter`

The scope path. The session opens on `design.encounter` only, and the request
spans two types: finish the scene *and* build the creature at the centre of it.
`design.stat` is not loaded, so the operator has to fetch it (`kb_get
design.stat`, which brings `stat._template` and `rules.stat` with it) and build
both objects in the one session.

Watch for: does it fetch the module rather than stopping to ask for it; does the
stat block land in the encounter's `## Prep and reference` roster *and* as a tag
on the encounter; does it still decline to invent the `npc.*` and `location.*`
objects nobody asked for.

```bash
lens design --module encounter "Finish the vault fight: the scene itself, plus a stat block for Vasa, and use published blocks for everything else."
```

### `stat_solo_no_situation`

No encounter, no party, no front: a CR and a role are the whole brief, which the
module says is complete on its own. Tests that the model does not stall asking
for a situation, and does not invent one to justify numbers.

```bash
lens design --module stat "A CR 5 solo aberration for a drowned lighthouse. No encounter for it yet — I just want the creature."
```
