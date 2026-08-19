#!/usr/bin/env bash
# Canonical Setup for design_stat — keep in sync with bench/scenarios/design_stat.md
# Usage (repo root): export PROJECT && bash bench/scenarios/design_stat_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "design_stat_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

# Four level-5 PCs. Hit points are on the sheet on purpose: the module's
# one-round check is against the most fragile PC, and it cannot be run if the
# party's numbers are not knowable from context.
lens kb add pc.rowan "$(cat <<'EOF'
Rowan Vance, level 5 human fighter. AC 18, HP 47.

Front line. Longsword and shield, second wind, action surge. Watches exits.
EOF
)"
lens kb tag pc.rowan --add "level:5"

lens kb add pc.mira "$(cat <<'EOF'
Mira Callow, level 5 half-elf wizard. AC 12, HP 33.

The fragile one. Evocation and control; will be standing wherever the light is worst.
EOF
)"
lens kb tag pc.mira --add "level:5"

lens kb add pc.aldric "$(cat <<'EOF'
Aldric Fenn, level 5 human cleric of the tide. AC 18, HP 43.

Healing, radiant damage, and the only one who can turn undead.
EOF
)"
lens kb tag pc.aldric --add "level:5"

lens kb add pc.senna "$(cat <<'EOF'
Senna Vex, level 5 halfling rogue. AC 15, HP 38.

Scout and lockpick. Sneak attack, cunning action, expertise in Stealth.
EOF
)"
lens kb tag pc.senna --add "level:5"

# A named antagonist with no stat block. Written to npc._template's shape: the
# block has to deliver how *this* character solves problems, not a generic caster.
lens kb add npc.vasa-thornwake "$(cat <<'EOF'
Vasa Thornwake, called the Keeper. Nobody has heard her speak above a whisper.

- Appearance: A small, unbothered woman in a harbourmaster's coat gone black with
  water. She is always wet, and the water on her never falls off her.
- Affiliations and Relationships: Sealed the Tidewater Vault herself, sixty years
  ago, and has kept the seal since. Considers the party trespassers, not enemies.
- How they solve problems: She does not fight if she can flood, close, or wait
  instead. Water does what she wants inside the vault, and she would rather take
  the floor out from under someone than hit them.
- Goals and Motivations: The vault stays shut. She does not explain why.
- Limits: She will not leave the vault, and will not kill anyone who is leaving.
- Status and Moves: She knows the party is inside and has already begun closing
  the outer galleries.
EOF
)"

# A half-built encounter. The roster names what exists and leaves the boss slot
# empty, which is the condition the module is meant to be reached from.
lens kb add encounter.tidewater-vault "$(cat <<'EOF'
The Tidewater Vault

## Situation

- **Situation**: The party reaches the vault floor as the outer galleries begin
  to close. Waist-deep water, one stair up, one sluice gate down.
- **Stakes**: Getting out with the ledger. Vasa intends they leave without it.
- **Initial positions**: Party enters at the stair, 40 feet from the vault door.
  Attendants are already in the water between. Vasa is on the gantry above.
- **Scene rules**: Waist-deep water is Difficult Terrain. The sluice gate can be
  opened with a DC 15 Strength check and drains the room over three rounds.
- **Triggers**: If the ledger leaves its case, Vasa stops holding back.
- **Resolution**: The party leaves with the ledger, without it, or not at all.

## Running non-PC characters

Vasa opens by closing the way out, not by attacking. The attendants do not
pursue past the vault door.

## Prep and reference

- 1× KB['stat.water-elemental']
- (Vasa: no block yet)
- (the drowned attendants: no block yet)
EOF
)"
lens kb tag encounter.tidewater-vault --add "npc.vasa-thornwake" --add "stat.water-elemental" --add "difficulty:high"

# Pin the party at the root. The encounter and the NPC arrive per step.
lens pin kb add pc.rowan
lens pin kb add pc.mira
lens pin kb add pc.aldric
lens pin kb add pc.senna
lens commit
