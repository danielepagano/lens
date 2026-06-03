#!/usr/bin/env bash
# Canonical Setup for edit_quality — keep in sync with bench/scenarios/edit_quality.md
# Usage (repo root): export PROJECT && bash bench/scenarios/edit_quality_setup.sh
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "edit_quality_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - location.registry
]: #

# default

The hall smelled of vinegar and sealing wax. Torches guttered along the cedar beams; clerks shuffled past with armloads of ribbon-tied folios, each one a small war of ink and precedent.

Martine stood at the counter with her hands flat on the deal-book. She was nervous. She was worried about the deal. She thought that the deal might be bad. She did not like feeling uncertain. The clerk waited for her seal, fingers tapping the brass edge in a rhythm that matched nothing in her chest.

Beyond the arch, someone laughed at a joke about taxes; the sound made her jaw ache. Wax dripped from a nearby taper; she watched it crawl, slow as a verdict.

The inkwell reflected the torchlight; she did not look up.
EOF
)"
lens commit
