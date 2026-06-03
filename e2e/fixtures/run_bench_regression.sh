#!/usr/bin/env bash
# Print bench regression commands (B-01–B-07). Does not invoke the LLM.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
echo "Bench regression scenarios (run manually or via agent; see bench/agent.md):"
for s in \
  remember_section \
  section_summary \
  advance_fronts \
  play_gm_voice \
  write_coherence \
  edit_quality \
  design_instructions
do
  echo ""
  echo "  B: bench/scenarios/${s}.md"
  echo "    PROJECT=\$(python bench/tools/setup_bench.py --profile local_thinking --scenario bench/scenarios/${s}.md)"
  echo "    export PROJECT && bash bench/scenarios/${s}_setup.sh  # if present"
done
