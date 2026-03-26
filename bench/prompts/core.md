# Lens Benchmark — Core Reference

Shared mechanics for all benchmark use cases. Read this first.

## Project setup

Create a benchmark project connected to a real LLM:

```bash
python bench/tools/setup_bench.py --profile local_thinking --scenario bench/scenarios/write_coherence.md
```

This prints the project directory. `cd` into it for all `lens` commands.
The LLM server must be reachable (local model running, or API key set).

To invoke `lens` from the bench project directory, add the poetry venv to PATH:

```bash
VENV="$(poetry env info -p)/bin"
cd /tmp/lens_bench_...
PATH="$VENV:$PATH" lens stats
```

## Scenario format

Each scenario is a Markdown file in `bench/scenarios/`. Structure:

| Section | Purpose |
|---------|---------|
| Title + description | What the scenario tests |
| `~~~config` block | Machine-readable: `datasets` (optional) |
| Setup | CLI commands to build narrative state (run once) |
| Steps | Benchmark operations to evaluate (each has an ID) |
| Evaluation criteria | Scoring rubric (1–5 scale) |
| Prompt iteration guidance | Focus key, goal, anti-patterns |

## Scoring scale

| Score | Meaning |
|-------|---------|
| 1 | Fails entirely — criterion not met at all |
| 2 | Weak — partially met with significant issues |
| 3 | Acceptable — does the job but room for improvement |
| 4 | Good — meets the criterion well |
| 5 | Excellent — hard to improve |

## Replay mechanics

Lens provides built-in replay so you never need to rebuild the project to
re-run a step.

| Command | Effect |
|---------|--------|
| `lens write --retry` | Discard current output, regenerate (same or new prompt) |
| `lens rollback` | Discard pending transaction entirely |
| `lens rewind /@cursor` | Clean up open tail at cursor |
| `lens rewind /` | Rewind to narrative root |
| `lens prompt set <key> "..."` | Override a prompt at project level |
| `lens prompt clear <key>` | Restore the default prompt |
| `lens prompt get <key>` | Print active prompt and its source layer |

**Key principle:** `--retry` is cheapest (no state change), `rollback` undoes
the current transaction, `rewind` goes back further. Start with `--retry`.

## Transactions between steps

Do **not** call `lens commit` between benchmark steps.  Operators
auto-progress within a transaction — a subsequent `lens write` continues
from where the last one left off.  Inserting commits hides
transaction-handling bugs, which defeats the purpose of the benchmark.

Only commit during **setup** (to stage KB/pin changes before the first
write) and at the **end** if you need to inspect final state.

## Report format

Write a JSON file to `bench/reports/` with this structure:

```json
{
  "meta": {
    "scenario_id": "write_coherence",
    "scenario_name": "Write with KB context",
    "timestamp": "2026-03-26T14:30:00Z",
    "llm_profile": "local_thinking",
    "llm_model": "qwen3-8b",
    "project_dir": "/tmp/lens_bench_..."
  },
  "steps": [
    {
      "step_id": "continue_unprompted",
      "command": ["write"],
      "description": "Continue without a prompt",
      "output": "Elena stepped beneath the canopy...",
      "output_length": 847
    }
  ],
  "evaluation": {
    "scores": [
      {
        "criterion": "KB integration: ...",
        "step_id": "continue_unprompted",
        "score": 4,
        "reasoning": "Character traits woven into action..."
      }
    ],
    "average_score": 4.2,
    "pass": true,
    "summary": "Strong KB awareness across both steps..."
  },
  "iterations": []
}
```

Render to HTML:

```bash
python bench/tools/report.py render bench/reports/your_report.json
```
