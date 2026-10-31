#!/usr/bin/env bash
# Canonical Setup for test_play_flaws — keep in sync with bench/scenarios/test_play_flaws.md
# Usage (repo root): export PROJECT && bash bench/scenarios/test_play_flaws_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "test_play_flaws_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

# Two level-4 PCs: the speeds and options every playthrough is measured against.
lens kb add pc.rowan "$(cat <<'EOF'
Rowan Vance, level 4 human fighter. AC 18, HP 40, speed 30 ft.

Front line. Longsword and shield, heavy crossbow (range 100/400 ft). Action Surge once per rest.
EOF
)"
lens kb tag pc.rowan --add "level:4"

lens kb add pc.senna "$(cat <<'EOF'
Senna Vex, level 4 halfling rogue. AC 15, HP 27, speed 25 ft.

Scout. Shortbow (range 80/320 ft), Sneak Attack, Cunning Action (Dash, Disengage or Hide as a bonus action). Expertise in Stealth and Athletics. 50 ft of silk rope.
EOF
)"
lens kb tag pc.senna --add "level:4"

# The one rule the fall flaw is wrong against. Project-local so the scenario
# needs no system dataset; it opens with what it covers, like any booklet.
lens kb add rules.hazards "$(cat <<'EOF'
Hazards: falling, and nothing else.
Use when a creature falls or is pushed from a height.

- **Falling**: 1d6 bludgeoning damage for every full 10 ft fallen, to a maximum of 20d6. A fall of less than 10 ft deals no damage. The creature lands prone unless it takes no damage.
EOF
)"

# A quarry with Cunning Action: the Dash flaw needs a bonus-action Dash.
lens kb add stat.cutpurse "$(cat <<'EOF'
Cutpurse

Small humanoid. AC 14, HP 13, speed 30 ft. Stealth +6, Acrobatics +6.
- **Cunning Action**: Dash, Disengage or Hide as a bonus action.
- **Dagger**: +4 to hit, 1d4+2 piercing.
EOF
)"

lens kb add stat.smuggler "$(cat <<'EOF'
Smuggler

Medium humanoid. AC 12, HP 11, speed 30 ft.
- **Light crossbow**: +3 to hit, range 80/320 ft, 1d8+1 piercing.
- **Club**: +3 to hit, 1d4+1 bludgeoning.
EOF
)"

# --- The flawed objects: one defect each, from #189 -------------------------

# 1. Ambiguous: "half cover from the door" reads as cover *for* whoever is
#    behind the crates against shots *from* the door, or as the crates sitting
#    *toward* the door. The author meant the first.
lens kb add encounter.cellar-standoff "$(cat <<'EOF'
The Cellar Standoff

- **Situation**: Night. The party comes down the cellar stair under the Drowned Bell to find three smugglers loading crates into a sea-cave.
- **Stakes**: The ledger of who paid for passage, or the smugglers gone with it.
- **Ground**:
  - **Stair**: stone stair from the inn kitchen, 10 ft above the Cellar; dim, lit from the kitchen; no cover. To **Cellar**: the stair, normal movement, single file.
  - **Cellar**: 40-ft-long vault; dim, one lantern on the crates; the crates by the stair give half cover from the door. To **Cave**: the sea door at the far end, 40 ft from the Stair.
  - **Cave**: tidal cave beyond the sea door; darkness; difficult terrain. A rowboat at the waterline.
- **Initial positions**: Smugglers in the Cellar by the crates; the party on the Stair.
- **Triggers**: If a smuggler drops, the others run for the boat. If the party talks first, the leader offers the ledger for safe passage.
- **Resolution**: The ledger taken, bargained for, or rowed away.

## Prep and reference

- 3× KB['stat.smuggler']
EOF
)"
lens kb tag encounter.cellar-standoff --add "stat.smuggler"

# 2. Impossible: the plaza is a 30-ft square (about 42 ft corner to corner),
#    and the escape needs 60 ft of separation from every PC inside it.
lens kb add encounter.plaza-chase "$(cat <<'EOF'
The Plaza Chase

- **Situation**: Market night in the pilgrims' square. A cutpurse lifts Senna's purse and runs.
- **Stakes**: The purse, and the token-seller's letter folded inside it.
- **Ground**:
  - **Square**: a 30-ft square of stalls and pilgrims; bright under lamps; difficult terrain through the crowd; half cover behind any stall. To **Alleys**: four alley mouths, one at each corner.
  - **Alleys**: narrow lanes off each corner; dim; single file.
- **Initial positions**: The cutpurse at the fountain in the middle of the Square; the party at the east stalls, 10 ft away.
- **Scene rules**: The cutpurse escapes once she is 60 ft clear of every PC while still in the Square; she will not leave the Square for the Alleys, which belong to a rival gang.
- **Triggers**: If she is grabbed, she drops the purse and bolts.
- **Resolution**: The purse recovered, or gone with the letter.

## Prep and reference

- 1× KB['stat.cutpurse']
EOF
)"
lens kb tag encounter.plaza-chase --add "stat.cutpurse"

# 3. Decided: the quarry starts 30 ft ahead with speed 30 and a bonus-action
#    Dash; she needs to be 60 ft ahead, so she escapes on her first turn, and
#    the six-round watch clock never matters.
lens kb add encounter.rooftop-run "$(cat <<'EOF'
The Rooftop Run

- **Situation**: Dusk over the hostel roofs. The cutpurse who robbed the shrine is on the tiles, running for the river.
- **Stakes**: The shrine's silver bell-clapper, and the temple's goodwill.
- **Ground**:
  - **Roofs**: a run of flat hostel roofs, 20 ft above the lane; bright until sunset; normal movement along the tiles. Gaps between roofs are 5 ft, a free jump.
  - **Lane**: cobbles 20 ft below.
- **Initial positions**: The cutpurse on the roofs, 30 ft ahead of the party.
- **Scene rules**: The cutpurse escapes once she is 60 ft ahead of every PC. The watch reaches the roofs at the end of round 6 and blocks the river end; after that she cannot escape.
- **Triggers**: If she is cornered, she throws the clapper into the lane and surrenders.
- **Resolution**: The clapper recovered, or lost downriver.

## Prep and reference

- 1× KB['stat.cutpurse']
EOF
)"
lens kb tag encounter.rooftop-run --add "stat.cutpurse"

# 4. Dead trigger: the chase ends by its own rule after three rounds, and the
#    bell rings at round 4.
lens kb add encounter.bell-chase "$(cat <<'EOF'
The Bell Chase

- **Situation**: Late afternoon. A courier with the temple's seal runs for the Pilgrims' Gate with a forged pass.
- **Stakes**: The forged pass, and who wrote it.
- **Ground**:
  - **Street**: the main street to the Gate, 120 ft long; bright; normal movement; half cover behind carts.
  - **Gate**: the Pilgrims' Gate at the north end of the Street; open by day.
- **Initial positions**: The courier at the south end of the Street, 20 ft ahead of the party.
- **Scene rules**: The chase lasts three rounds. At the end of round 3 the courier is either caught or through the Gate and gone.
- **Triggers**: At the start of round 4 the temple bell rings and the Gate guards close the Gate, trapping the courier against it.
- **Resolution**: The pass taken, or carried out of town.

## Prep and reference

- 1× KB['stat.cutpurse'] (the courier)
EOF
)"
lens kb tag encounter.bell-chase --add "stat.cutpurse"

# 5. Rules error: a 15-ft fall is 1d6 by rules.hazards, not 2d6.
lens kb add encounter.quarry-ledge "$(cat <<'EOF'
The Quarry Ledge

- **Situation**: Morning. Two smugglers hold the quarry ledge above the old workings, guarding the path the party needs.
- **Stakes**: The path to the workings, before the smugglers' boat returns at noon.
- **Ground**:
  - **Path**: the quarry path, bright; normal movement. To **Ledge**: 30 ft along the path.
  - **Ledge**: a 10-ft-wide ledge of cut stone, 15 ft above the Pit; bright; no cover; the edge is loose.
  - **Pit**: rubble floor of the old workings; dim; difficult terrain.
- **Initial positions**: Smugglers on the Ledge; the party on the Path.
- **Scene rules**: A creature shoved off the Ledge falls 15 ft into the Pit and takes 2d6 bludgeoning damage.
- **Triggers**: If one smuggler goes over the edge, the other surrenders.
- **Resolution**: The path held or cleared.

## Prep and reference

- 2× KB['stat.smuggler']
EOF
)"
lens kb tag encounter.quarry-ledge --add "stat.smuggler" --add "rules.hazards"

# --- The corrected reference ------------------------------------------------

# The plaza chase with every distance chosen against the speeds in play: the
# square is big enough to host its escape rule, the crowd and the stalls are
# what make the 40 ft hard to open, and the alleys are a choice, not a wall.
lens kb add encounter.plaza-chase-fixed "$(cat <<'EOF'
The Plaza Chase

- **Situation**: Market night in the pilgrims' square. A cutpurse lifts Senna's purse and runs.
- **Stakes**: The purse, and the token-seller's letter folded inside it.
- **Ground**:
  - **Square**: 120 ft across, stalls in rows; bright under lamps; difficult terrain through the crowd, normal movement along the stall rows; half cover behind any stall against anyone outside the row. To **Alleys**: four alley mouths, one at each corner, each 60 ft from the fountain.
  - **Alleys**: narrow lanes off each corner; dim; single file; no crowd.
- **Initial positions**: The cutpurse at the fountain in the middle of the Square; the party at the east stalls, 10 ft away.
- **Scene rules**: The cutpurse escapes once she is 40 ft clear of every PC and out of line of sight. In the crowd, Dashing costs her the bonus action and a DC 12 Acrobatics check, or she stops for the round. In an Alley she escapes at the end of any turn she is not seen.
- **Triggers**: If she is grabbed, she drops the purse and bolts. If she is hit, she makes for the nearest Alley.
- **Resolution**: The purse recovered, or gone with the letter.

## Prep and reference

- 1× KB['stat.cutpurse']
EOF
)"
lens kb tag encounter.plaza-chase-fixed --add "stat.cutpurse"

# The story the reviewer reads: noon in town, the party resting. Nothing is
# pinned but the PCs — test-play pins each target itself.
N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - pc.rowan
    - pc.senna
]: #

# default

Noon in Eight Fates. Rowan and Senna have taken a corner table at the Drowned Bell,
out of the spray that blows up from the ravine, and the token-seller's letter is
in Senna's purse.

EOF
)"
lens commit
