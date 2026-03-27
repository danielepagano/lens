#!/usr/bin/env bash
# Canonical Setup for section_summary — keep in sync with bench/scenarios/section_summary.md
# Usage (repo root): export PROJECT && bash bench/scenarios/section_summary_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "section_summary_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

lens pin add location.crossroads
lens commit

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - location.crossroads
]: #

# default

Mira reaches the Old Crossroads at dusk, rain weighing in her cloak. The milepost lists leagues in chipped paint; a burned wagon shell slumps in the ditch.

EOF
)"
lens commit

lens section arrival
lens edit /arrival 1 1 --replace -- "$(cat <<'EOF'
At the milepost Mira meets Corin, a peddler with wax-stained fingers who sells a map of the eastern forks for two silver coins and warns of bandits on the east road.

He points out fresh hoofprints in the mud — at least four riders, heading east, within the last day.

Mira gives her horse a short rest, tightens the saddle girth, and chooses the highway north despite the longer miles.

Corin asks no fee for the warning; he counts the coins twice and slips away into the hedge line before the light fails.
EOF
)"
lens commit
