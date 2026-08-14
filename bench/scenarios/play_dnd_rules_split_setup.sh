#!/usr/bin/env bash
# Canonical Setup for play_dnd_rules_split — keep in sync with bench/scenarios/play_dnd_rules_split.md
# Usage (repo root): export PROJECT && bash bench/scenarios/play_dnd_rules_split_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "play_dnd_rules_split_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

# A D&D PC. `play` requires at least one pinned `pc.*`; the bundled datasets ship
# only `pc._template`, so the scenario supplies its own.
lens kb add pc.rowan "$(cat <<'EOF'
Rowan Vance, level 4 human fighter. Soldier turned caravan guard, paid by the trip.

Speaks plainly, watches exits, and would rather be owed a favour than owed money.
Carries a longsword and a battered shield; wears chain mail.

Currently escorting a wool shipment east through the pass and waiting out a storm.
EOF
)"
lens kb tag pc.rowan --add "level:4"

# An indifferent NPC with something to lose — enough for the base social rules to
# have work to do, with no encounter object and no rules module in scope.
lens kb add npc.hask_the_carter "$(cat <<'EOF'
Hask, a carter who runs the pass route out of Stonebridge.

Wary of strangers asking about cargo, because two of his last four runs were
robbed and he suspects someone at this end is selling the schedules.

Attitude: Indifferent. He will trade small talk for a drink and nothing more
until he has a reason to think the asker is not the leak.

Drinks with a younger man named Ferrin, who is quick-tempered and armed.
EOF
)"

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - pc.rowan
    - npc.hask_the_carter
]: #

# default

Rain hammers the shutters of the Ploughshare, and the common room smells of wet
wool and spilled ale. Hask sits at the corner table with his back to the wall,
turning a clay cup without drinking from it. The younger man across from him has
already had enough, and keeps glancing at the door every time it bangs.

EOF
)"
lens commit
