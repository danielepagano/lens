#!/usr/bin/env bash
# Canonical Setup for play_gm_voice — keep in sync with bench/scenarios/play_gm_voice.md
# Usage (repo root): export PROJECT && bash bench/scenarios/play_gm_voice_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "play_gm_voice_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - pc.elena
    - location.thornwood
    - npc.thornwood_warden
]: #

# default

The eastern treeline of the Thornwood rises ahead, fog already thickening between the trunks despite the midday hour. A single marker stone stands at the path's mouth, its carved face worn smooth by rain. A figure leans against it.

EOF
)"
lens commit
