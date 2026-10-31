#!/usr/bin/env bash
# Canonical Setup for ground_ravine — keep in sync with bench/scenarios/ground_ravine.md
# Usage (repo root): export PROJECT && bash bench/scenarios/ground_ravine_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "ground_ravine_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

# Two level-4 PCs. `play` requires at least one pinned `pc.*`.
lens kb add pc.rowan "$(cat <<'EOF'
Rowan Vance, level 4 human fighter. AC 18, HP 40, speed 30 ft.

Front line. Longsword and shield, heavy crossbow for range. Watches exits.
EOF
)"
lens kb tag pc.rowan --add "level:4"

lens kb add pc.senna "$(cat <<'EOF'
Senna Vex, level 4 halfling rogue. AC 15, HP 27, speed 30 ft.

Scout. Shortbow, Sneak Attack, Cunning Action, expertise in Stealth and Athletics.
Has 50 ft of silk rope and a grappling hook.
EOF
)"
lens kb tag pc.senna --add "level:4"

# The town the ravine belongs to: ordinary location prose, parent of the ravine.
lens kb add location.eight-fates "$(cat <<'EOF'
Eight Fates

- Type: a shrine-town of pilgrims' hostels on the high moor, at the head of the ravine that shares its name.
- Sensory feel: prayer-strips snapping on every line, peat smoke, bells nobody admits to ringing.
- Social feel: pilgrims, guides who overcharge, and a temple that sells passage tokens to the Gate.
- What the place does: no token, no guide; nobody in town will lead an unsanctioned party down.
- Tensions: the gnolls in the ravine have taken two guided parties this month, and the temple has not closed the Gate path.
EOF
)"

# The ravine as a location: durable prose only. The ground the scene is played
# on lives in the encounter.
lens kb add location.fates-ravine "$(cat <<'EOF'
The Ravine of Eight Fates

- Type: a sheer gorge below the town, running north to the Gate the pilgrims come for.
- Sensory feel: the river loud enough to drown a shout; cold spray; carrion birds on the west wall.
- Why it matters: the only way to the Gate, and the gnolls have taken the old den on the west wall.
- What the place does: the floor never reaches the Gate. Whoever holds the Den sees every step of the descent.
EOF
)"
lens kb tag location.fates-ravine --add "location.eight-fates"

# The encounter, carrying the reference Ground: every distance chosen at a
# threshold, and the three contradictions in the original freehand prep (see
# the scenario's intro) cannot be written in this form. Ground is the place,
# not the scene: the gnolls' rope is a scene rule naming zones, and nobody's
# position is in it. No initial positions either; the Situation and the first
# beat place everyone.
lens kb add encounter.ravine-approach "$(cat <<'EOF'
The Ravine Approach

## Situation

- **Situation**: Early afternoon. The party starts down the Ravine of Eight Fates for the Gate, without a guide or a token. Two gnoll warriors hold the Den lip on the west wall and watch the descent; their two hyenas are held on the Floor below it, out of sight of the Rim.
- **Stakes**: Reaching the Gate before dark, or being pinned on the east wall when the light goes.
- **Ground**:
  - **Rim**: trailhead on the east rim, 60 ft above the Floor; bright by day; open, half cover behind the waymark cairn. To **Ledge**: the cut stair, normal movement, single file. **Den** is 125 ft across, in plain sight.
  - **Ledge**: 5-ft stair on the east wall, 30 ft above the Floor; bright until mid-afternoon, then dim; no cover. To **Switchbacks**: climb, DC 10 Athletics, single file. **Den** is 120 ft across the gorge, in plain sight. **Floor**: only by falling.
  - **Switchbacks**: goat track in the scree under the Ledge, 10 ft above the Floor; dim; difficult terrain; half cover behind boulders, three-quarters against the Den. To **Floor**: the last turn, difficult terrain. **Den** is 90 ft across.
  - **Floor**: shingle and shallow fast water; dim by day, darkness after sunset; difficult terrain. To **Den**: climb, DC 15 Athletics. To **Gate**: no way on foot; the Floor ends in the Sump, swim DC 12 Athletics, then climb DC 15 Athletics.
  - **Den**: cave mouth on the west wall, 30 ft above the Floor; dim at the lip, darkness inside; half cover at the lip. To **Gate**: the west shelf, normal movement, single file.
  - **Gate**: iron-bound door at the north end, 20 ft above the Floor; dim; total cover inside the arch. **Ledge** is 90 ft down-gorge, in plain sight.
- **Scene rules**: The gnolls' knotted rope hangs from the Den lip: while it is down, the Floor to the Den is climb, DC 10 Athletics; hauling it up takes one action from the lip. The gnolls shoot at anyone on the Ledge or the Switchbacks and never at the Rim.
- **Triggers**: If anyone reaches the Switchbacks, the hyenas are loosed along the Floor. If a gnoll drops below half HP, the other hauls up the rope and holds the Den. If the party reaches the west shelf, both gnolls fall back inside.
- **Resolution**: The party reaches the Gate, turns back to Eight Fates, or is pinned until dark. The Den taken or left holding changes who controls the descent for the next party.

## Running non-PC characters

Gnolls stay at the Den lip and shoot; they do not come down while the rope is up. Hyenas hunt the Floor and the last turn of the Switchbacks only, and flee when one of them drops.

## Prep and reference

- 2× KB['stat.gnoll-warrior']
- 2× KB['stat.hyena']
EOF
)"
lens kb tag encounter.ravine-approach \
  --add "location.fates-ravine" \
  --add "stat.gnoll-warrior" --add "stat.hyena" \
  --add "rules.combat" --add "difficulty:moderate"

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - pc.rowan
    - pc.senna
    - encounter.ravine-approach+
]: #

# default

The waymark cairn at the head of the ravine is hung with prayer-strips gone grey
in the spray. Below, the gorge drops away north toward the Gate, and somewhere
down there the river is louder than anything either of you could shout over.

EOF
)"
lens commit
