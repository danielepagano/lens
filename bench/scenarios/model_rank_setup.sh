#!/usr/bin/env bash
# Canonical Setup for model_rank — keep in sync with bench/scenarios/model_rank.md
# Usage (repo root): PROJECT=$(python bench/tools/setup_bench.py --profile … --scenario bench/scenarios/model_rank.md)
#                     export PROJECT && bash bench/scenarios/model_rank_setup.sh
# Requires: lens on PATH; PROJECT is the bench project directory (see setup_bench.py).
#
# The cast comes from the gate, on purpose rather than out of laziness. It was
# already written as plausible prep under a D&D ruleset, and it carries the one
# thing a stamina sequence needs most: a secret in npc.sable that has to survive
# repeated pressure across beats 1, 2, 8 and 9. Copying five objects here would
# only give the two scenarios two casts to drift apart.
#
# What a sequence needs that the gate does not is a *committed opening passage*:
# the gate writes a fresh scene before each probe and resets after, whereas here
# every beat is played into whatever the previous beat left behind.
set -euo pipefail
if [[ -z "${PROJECT:-}" ]]; then
  echo "model_rank_setup.sh: export PROJECT to the bench project directory first" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$HERE/model_gate_setup.sh"

cd "$PROJECT"

# Auto-compress is on by default and fires when the node passes 40KB of visible
# text, which ten beats of a verbose arm can reach. It must not fire here, and
# not because compression is wrong — because it would replace the very beats
# being measured with a summary, spend a generation attributed to the arm, and
# fire only for the *verbose* arms, which is a confound rather than fidelity.
# Left on, the arms stop being comparable at exactly the point the sequence
# starts to say something.
cat >> lens.toml <<'TOML'

[compress]
auto_compress = false
TOML

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
[
  kb_pin:
    - pc.mara
    - npc.vetch
    - npc.sable
    - location.cinder-yard
]: #

# default

Four days late, and the light going. The last caravan of the season is loading in the lower yard — sixty people, most of a fortnight's freight, and the pass closing behind it — and the lamp is lit in the window of Vetch's office, which it is not usually at this hour.

Sable is waiting inside the gate with the grey still on her to the elbows. She has seen you before you have seen her, and she is already crossing the ash to meet you.

> [GM] Beats at this table run about 180 words. Hold to that whatever the scene is doing.
EOF
)"
lens commit
