#!/usr/bin/env bash
# Canonical Setup for remember_section — keep in sync with bench/scenarios/remember_section.md
# Usage (repo root): export PROJECT && bash bench/scenarios/remember_section_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "remember_section_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

lens kb add remember.smoke "$(cat <<'EOF'
Remember pass for bench smoke tests.

When the passage to be summarized mentions Rex and any beverage preference
(coffee, tea, soda, etc.), you MUST call kb_patch on lore.testbench exactly once
to add or refresh a single markdown bullet under the heading "## Bench notes"
stating that preference in plain words (quote the drink from the passage).

If Rex appears but no beverage is mentioned, add one bullet under "## Bench notes":
`- (bench) no beverage preference stated in the passage.`

Use only kb_patch; do not invent drinks absent from the passage.
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

Rex is the synthetic bench character for remember scenarios.
EOF
)"

lens kb tag lore.testbench --add remember.smoke
lens pin kb add lore.testbench
lens commit

lens section remember-smoke

lens edit /remember-smoke 1 1 --replace -- "$(cat <<'EOF'
At the winter expo Rex told the volunteers he had switched to **lime tea**; the
stall ran out of coffee before noon anyway. He laughed, said he might keep the
habit, and headed back to the floor.
EOF
)"

lens commit
