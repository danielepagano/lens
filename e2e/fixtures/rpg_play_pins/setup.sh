#!/usr/bin/env bash
# Regression fixture: RPG play pins (testing dataset objects). Requires PROJECT.
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "rpg_play_pins/setup.sh: export PROJECT first" >&2
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

The eastern treeline of the Thornwood rises ahead, fog thickening between the trunks.
EOF
)"
lens commit
