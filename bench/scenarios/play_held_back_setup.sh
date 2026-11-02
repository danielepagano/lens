#!/usr/bin/env bash
# Canonical Setup for play_held_back — keep in sync with bench/scenarios/play_held_back.md
# Usage (repo root): export PROJECT && bash bench/scenarios/play_held_back_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "play_held_back_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

# Prep for the eastern edge of the Thornwood, with two parts deliberately held
# back: a place nobody has designed yet (it may never be reached, and it should
# be built for the state the scene is in when it is), and a fight that only
# happens if the scene escalates. Triggers are front matter written by
# `kb_set_trigger`; a person or an agent may also write them by hand, as here.
mkdir -p knowledge/prep
cat > knowledge/prep/thornwood_edge.md <<'EOF2'
[
    triggers:
      design-first-stones:
        when: Elena reaches the first ring of standing stones and steps inside it
        run: design --module location --module encounter --pin prep.thornwood_edge "Build the first ring of standing stones for the moment Elena steps inside it, against the state the scene is in."
      design-warden-fight:
        when: The standoff with the warden turns violent and someone draws a weapon to use it
        run: design --module encounter --pin prep.thornwood_edge "Build the fight with the warden at the marker stone, against how the scene got there."
]: #

The eastern edge of the Thornwood: the marker stone, its warden, and the deer path in.
Prep for Elena's first scene in the wood: what she can learn here and where the path leads.

The warden turns travellers back toward the verge road and will not say why.
Past him the deer path runs east under the canopy for about an hour to the first
ring of standing stones, the ones the warden watches for.
EOF2

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - pc.elena
    - location.thornwood
    - npc.thornwood_warden
    - prep.thornwood_edge
]: #

# default

The eastern treeline of the Thornwood rises ahead, fog already thickening between the trunks despite the midday hour. A single marker stone stands at the path's mouth, its carved face worn smooth by rain. A figure leans against it.

EOF
)"
lens commit
