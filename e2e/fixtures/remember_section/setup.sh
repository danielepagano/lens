#!/usr/bin/env bash
# Regression fixture: remember at section close. Requires PROJECT and lens on PATH.
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "remember_section/setup.sh: export PROJECT first" >&2
  exit 1
fi
cd "$PROJECT"

lens kb add remember.smoke "$(cat <<'EOF'
Remember pass for regression tests.

When the passage mentions Rex and any beverage preference, call kb_patch on
lore.testbench once to add a bullet under "## Bench notes" stating that preference.
EOF
)"

lens kb template smoke "$(cat <<'EOF'
## Bench notes

-

EOF
)"

lens kb add lore.testbench "$(cat <<'EOF'
## Bench notes

_(Remember pass will edit this section.)_

## Character

Rex is the synthetic regression character.
EOF
)"

lens kb tag lore.testbench --add remember.smoke
lens pin kb add lore.testbench
lens commit

lens section remember-smoke

lens edit /remember-smoke 1 1 --replace -- "$(cat <<'EOF'
At the winter expo Rex told the volunteers he had switched to **lime tea**; the
stall ran out of coffee before noon anyway.
EOF
)"

lens commit
