# Use Case: Compare LLMs

Run the same scenario against different models, compare scores side-by-side.

Prerequisite: read `core.md` for setup and scoring mechanics.

## Steps

1. **For each LLM profile**, create a separate project and run the full scenario:

```bash
python bench/tools/setup_bench.py --profile local_thinking --scenario bench/scenarios/write_coherence.md
# cd into project, run setup + steps, evaluate, produce report JSON

python bench/tools/setup_bench.py --profile grok --scenario bench/scenarios/write_coherence.md
# cd into project, run same scenario, produce report JSON
```

2. **Render comparison:**

```bash
python bench/tools/report.py compare bench/reports/run_a.json bench/reports/run_b.json
```

This produces a side-by-side HTML with per-criterion scores and deltas.

## Tips

- Use the same scenario and evaluation criteria for every model — only the
  LLM profile should change.
- Run each model 2–3 times (`--retry`) to account for variance before scoring.
- Name report files clearly: `write_coherence_qwen3-8b.json`, etc.
