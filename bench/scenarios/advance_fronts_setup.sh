#!/usr/bin/env bash
# Canonical Setup for advance_fronts — keep in sync with bench/scenarios/advance_fronts.md
# Usage (repo root): PROJECT=$(python bench/tools/setup_bench.py --profile … --scenario bench/scenarios/advance_fronts.md)
#                     export PROJECT && bash bench/scenarios/advance_fronts_setup.sh
# Requires: lens on PATH; PROJECT is the bench project directory (see setup_bench.py).
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "advance_fronts_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi
cd "$PROJECT"

lens kb add timeline.vale "# The Thornvale Chronicle

- Started: 3rd of Ashmonth
- Day: 1"

lens kb add front.blight "# The Spreading Blight

- Problem: A grey fungal rot is spreading from the old mill pond outward through Thornvale's fields. Left unchecked it will ruin the harvest.
- Stakes if ignored: Famine in Thornvale within a few weeks; villagers will flee or starve.
- Known to PCs: They have seen the grey patches and the dying crops around the mill pond.
- Phases:
  - Phase 1 (days 1–5): Creeping — rot within 100m of the mill pond; one field affected.
  - Phase 2 (days 6–10): Advancing — rot reaches the granary road; two fields affected; villagers begin to panic.
  - Phase 3 (day 11+): Critical — rot reaches the village well; three fields affected; council calls for evacuation.
- Chance mechanic: Every day (day mod 2 == 0), there is a 30% chance that a farmer's animal dies visibly from the blight, causing morale to drop and adding pressure on the council to act.
- Possible resolutions: Finding and destroying the source at the mill pond; a druid ritual the party has a lead on.

<!-- ai:secret: Gur oyvtug vf abg shapny — vg vf n zntvpny pbagntvba fcernqvat sebz n ohevq negvsnpg haqre gur zvyy cbaq. Qrfgeblvat gur negvsnpg fgbcf vg vzzrqvngryl. -->"

lens kb add front.courier "# The Overdue Courier

- Problem: A courier carrying a sealed letter from Lord Ashveil's estate went missing on the valley road three days before the adventure started. The letter contained a warning the party has not yet read.
- Stakes if ignored: The party acts without crucial intelligence; Lord Ashveil sends a second messenger who will arrive at day 8 and make things politically complicated.
- Known to PCs: They know a courier was expected; they do not know what the letter said or that the courier is in trouble.
- Phases:
  - Day 1–4: Courier is being held at the miller's abandoned barn (not yet known to PCs).
  - Day 5: If not rescued, the courier escapes on their own and reaches the village. They are shaken and the letter is gone (taken by the captors).
  - Day 8: Lord Ashveil's second messenger arrives regardless of prior events.
- Possible resolutions: Party finds the barn and rescues the courier before day 5; or the courier escapes on day 5 and delivers what they remember verbally.

<!-- ai:secret: Gur pbhevre vf orvat uryq ol gur fnzr tebhc gung ohevrq gur negvsnpg — gurl qba'g jnag gur jneavat ernpuvat gur cnegl. -->"

lens kb tag front.blight --add timeline.vale
lens kb tag front.courier --add timeline.vale

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - timeline.vale
]: #

# default

The party makes camp at the edge of the mill pond as the grey afternoon light fades. The smell of rot is faint but present. Tomorrow they plan to investigate.

EOF
)"
lens commit
