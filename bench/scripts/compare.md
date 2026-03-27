# Use Case: Compare LLMs

Run the same scenario against different models, compare scores side-by-side.

Prerequisite: read `bench/agent.md` for setup and scoring mechanics.

## Steps

1. **For each LLM profile**, create a separate project and run the full scenario:

```bash
python bench/tools/setup_bench.py --profile local_thinking --scenario bench/scenarios/write_coherence.md
# cd into project, run setup + steps, evaluate, then report.py init + complete report (merge or render/sync) — see bench/agent.md

python bench/tools/setup_bench.py --profile grok --scenario bench/scenarios/write_coherence.md
# same scenario; report.py init with --profile grok, then fill steps/evaluation (merge recommended)
```

2. **Render comparison:**

```bash
python bench/tools/report.py compare bench/reports/run_a.json bench/reports/run_b.json
```

Paths are resolved **relative to the repository root** (as with `report.py merge` / `validate`). Absolute paths work too.

This produces a side-by-side HTML with per-criterion scores and deltas (default output: **`comparison.html`** next to the first report path unless **`-o`** is set).

## Tips

- Use the same scenario and evaluation criteria for every model — only the
  LLM profile should change.
- Run each model 2–3 times (`--retry`) to account for variance before scoring.
- Name report files clearly: `write_coherence_qwen3-8b.json`, etc.
