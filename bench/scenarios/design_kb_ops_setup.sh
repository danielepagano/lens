#!/usr/bin/env bash
# Canonical Setup for design_kb_ops — keep in sync with bench/scenarios/design_kb_ops.md
# Usage (repo root): PROJECT=$(python bench/tools/setup_bench.py --profile … --scenario bench/scenarios/design_kb_ops.md)
#                     export PROJECT && bash bench/scenarios/design_kb_ops_setup.sh
# Requires: lens on PATH; PROJECT is the bench project directory (see setup_bench.py).
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "design_kb_ops_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

lens kb add timeline.vale "# The Thornvale Chronicle

- Started: 3rd of Ashmonth
- Day: 1"

# Deliberately long: the point of the scenario is editing material that already
# exists, and a short object would hide the difference between a patch and a
# whole-body rewrite.
lens kb add front.blight "# The Spreading Blight

- Problem: A grey fungal rot is spreading from the old mill pond outward through Thornvale's fields. Left unchecked it will ruin the harvest.
- Stakes if ignored: Famine in Thornvale within a few weeks; the granary road closes and villagers flee or starve.
- Known to PCs: They have seen the grey patches and the dying crops around the mill pond.
- Phases:
  - Phase 1 (days 1-5): Creeping — rot within 100m of the mill pond; one field affected.
  - Phase 2 (days 6-10): Advancing — rot reaches the granary road; two fields affected; villagers begin to panic.
  - Phase 3 (day 11+): Critical — rot reaches the village well; three fields affected; council calls for evacuation.
- Chance mechanic: Every day (day mod 2 == 0), there is a 30% chance a farmer's animal dies visibly from the blight, dropping morale and pressing the council to act.
- What a day costs it: one phase step every five days unless the party slows it.
- Possible resolutions: Finding and destroying the source at the mill pond; a druid ritual the party has a lead on.
- Cast: Miller Oswin (saw it first, will not say so), Councillor Bray (wants it denied until the harvest is in).
- Places: the mill pond, the granary road, the village well."

lens kb add npc.oswin "# Miller Oswin

- Wants: for nobody to ask when he first noticed the grey.
- Will not: admit he drained the pond into the east field.
- In a scene: answers the question before the one he was asked."

lens pin kb add pc.party || true
