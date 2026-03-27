# Lens benchmark — agent run

Task brief for any automated or semi-automated run (Cursor agent, script, or human checklist).

## What a run is

1. **Start from this file** — `bench/agent.md` is the entry point; read it before executing a benchmark.
2. **Required inputs:**
   - **Script** — the workflow you are running from `bench/scripts/` (this file is only shared mechanics): [baseline](scripts/baseline.md) (end-to-end run and scores), [compare](scripts/compare.md) (two LLMs side by side), [iterate](scripts/iterate.md) (prompt tuning). Pick one, then follow it **and** the steps below.
   - **Scenario** — `bench/scenarios/<name>.md` (setup, steps, rubric).
   - **LLM profile** — name or path under `bench/llm_profiles/<name>.toml`.
   - **User instructions** — any extra constraints for this run (optional).
3. **Run lens from a shell** — After `setup_bench.py` prints `PROJECT`, `cd` there and invoke `lens` in that same shell so **environment variables** (API keys, `PATH`) and **network** reach the LLM as intended. `lens` commands always run from `$PROJECT`; `report.py` always runs from the **repo root** (it resolves `bench/…` paths relative to the repo). Run **`lens check`** to verify `lens.toml`, keys (if any), bundled datasets, and the active narrative; **if it fails, stop and report** — do not treat the benchmark as valid.
4. **Create a report** — `report.py init`, then fill `steps` and `evaluation` and keep JSON and HTML consistent (see below).

A run is **not finished** while `steps` / `evaluation` are empty or while HTML is stale relative to the final JSON.

## Required outputs

| Artifact | Requirement |
|----------|---------------|
| **`bench/reports/…json`** | `steps` has one entry per scenario step with `output` (and `command` / `tokens` when known). `evaluation` has `scores`, `average_score`, `pass`, `summary`. |
| **`bench/reports/…html`** | Regenerated from that same JSON (same basename, `.html`). Stale HTML after JSON edits is a **failed** handoff. |

**Do not** hand off an `init`-only skeleton as the final report.

**Tools:** `report.py init` creates paths + skeleton HTML; **`report.py merge`** applies a JSON patch (`steps`, `evaluation`, …) and **re-renders HTML in the same invocation**; **`report.py sync`** re-renders when JSON is newer than HTML; **`report.py render`** forces HTML from JSON; **`report.py validate`** checks required fields (optional **`--scenario`** to match step IDs to the scenario’s **`## Steps`** section).

## Report contract (read before handoff)

### When to run `report.py init`

Run **`init` after** you know **`$PROJECT`** (post-`setup_bench`) and **after** the benchmark **`lens` steps** if you want the report **`meta.timestamp`** to bracket the run. Either order is fine; **`init` does not** need to precede the LLM calls.

### `merge` replaces top-level keys

**`merge`** loads the report JSON, applies the patch object, and writes the file back. **`meta`** is **shallow-merged** (patch keys update `meta`). **Every other top-level key** in the patch **replaces** the existing value (`steps`, `evaluation`, …). To change one step, **merge a full `steps` array** — there is no per-step deep merge. **Merging a partial `steps` array silently discards all other steps.** When in doubt, read the existing JSON first and include all steps in your patch.

### `evaluation.pass`

**`pass`** is **boolean** (never `null`). It is the evaluator’s judgment for this run. **Convention:** **`true`** when **`average_score` ≥ 3.0** and **no criterion is scored 1** (adjust if the scenario defines a different bar). Document overrides in **`meta.notes`**.

### Failed or partial runs

If **`lens check`** fails or a step errors before usable output, still **complete the report** when you need a record: use **`steps[].error`** (non-empty string) **instead of** **`steps[].output`** for that step, and set **`evaluation.pass`** / scores / summary to match reality. Prefer **`meta.notes`** for provider errors (e.g. HTTP 503) and retries.

### Validation

A freshly `init`-ed skeleton will fail `validate` (`evaluation.pass` is `null`, `steps` is empty). That is expected — `validate` is a **handoff check**, not a progress check. Run it only after filling `steps` and `evaluation`.

Before handoff:

```bash
python bench/tools/report.py validate bench/reports/<your_report>.json \
  --scenario bench/scenarios/<scenario>.md
```

Exit code **0** means required fields are present and, with **`--scenario`**, report **`steps[].step_id`** values match the scenario **Steps** section (each benchmark step is a Markdown heading of the form ``### `step_id` ``). Fix reported issues and re-run **`merge`** / **`sync`** as needed.

## End-to-end flow

1. `python bench/tools/setup_bench.py --profile <profile> --scenario bench/scenarios/<scenario>.md` → capture printed **`PROJECT`**.
2. **`cd "$PROJECT"`** — all `lens` commands run from here, in a **shell** (see above).
3. **`lens check`** — must pass before you rely on the project.
4. Follow your **script** and the **scenario**: run Setup once, then each step (see scenario format below).
5. **`python bench/tools/report.py init --scenario … --profile … --project-dir "$PROJECT"`** → keep the JSON path it prints (including the **repo-relative** line for copy-paste). Optional **`-o …`** if you want a chosen filename instead of the timestamped default.
6. **Fill the report** — run **`merge`** / **`sync`** / **`render`** on **that same JSON** (the `.html` sits beside it), e.g. **`python bench/tools/report.py merge <path> < patch.json`**.
7. Confirm the HTML mtime is **at or after** the JSON after the final fill.
8. Run **`report.py validate`** on the final JSON (with **`--scenario`** when possible).

Verification (`<your_report>` = the JSON basename from step 5, or your `-o` path):

```bash
python bench/tools/report.py sync bench/reports/<your_report>.json
```

If JSON was edited but HTML was stale, `sync` re-renders.

## Project setup

`setup_bench.py` prints a directory (default `bench/projects/lens_bench_*`, gitignored). The project is **empty** except an active narrative `default`; each scenario’s **Setup** adds KB and prose. The LLM server must be reachable. Use **`--print-env`** to also emit a shell-safe **`export PROJECT=…`** line on **stderr** (stdout remains the path alone for `PROJECT=$(…)`).

If `lens` is not on `PATH`, use the Poetry venv:

```bash
VENV="$(poetry env info -p)/bin"
cd "$PROJECT"
PATH="$VENV:$PATH" lens stats
```

## Scenario format

| Section | Purpose |
|---------|---------|
| Title + description | What the scenario tests |
| ` ```config` block | Machine-readable: `datasets` (optional) |
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

| Command | Effect |
|---------|--------|
| `lens write --retry` | Discard current output, regenerate (same or new prompt) |
| `lens rollback` | Discard pending transaction entirely |
| `lens rewind /@cursor` | Clean up open tail at cursor |
| `lens rewind /` | Rewind to narrative root |
| `lens prompt set <key> "..."` | Override a prompt at project level |
| `lens prompt clear <key>` | Restore the default prompt |
| `lens prompt get <key>` | Print active prompt and its source layer |

**Key principle:** `--retry` is cheapest (no state change), `rollback` undoes the current transaction, `rewind` goes back further. Start with `--retry`.

## `lens commit` — what it means

`lens commit` closes the current **narrative transaction**: it stages all pending file changes (`git add -A`) so the next operator starts a fresh transaction. It does **not** create a git commit. Think of it as "seal this batch of changes before writing more."

## Transactions between steps

Do **not** call `lens commit` between benchmark steps. Operators auto-progress within a transaction — a subsequent `lens write` continues from where the last one left off. Inserting commits hides transaction-handling bugs.

Only commit during **setup** (to seal KB and prose changes before the first write) and at the **end** if you need to inspect final state.

## Report workflow detail

### Init

```bash
python bench/tools/report.py init \
  --scenario bench/scenarios/<scenario>.md \
  --profile <profile> \
  --project-dir "$PROJECT"
```

Writes `bench/reports/<scenario>_<profile>_<UTC stamp>.json` and skeleton HTML. **The run is not done yet.**

### Fill (required)

Populate `steps` and `evaluation` using the scenario’s step IDs and criteria.

**Preferred:** merge a patch (JSON + HTML stay in sync):

```bash
python bench/tools/report.py merge bench/reports/your_report.json < patch.json
```

`patch.json` is a JSON object; typical keys are `"steps"`, `"evaluation"`, and optional `"meta"` (merged into existing `meta`).

**Alternative:** hand-edit the JSON, then `render` or `sync` (see verification above).

### Example JSON shape

```json
{
  "meta": {
    "scenario_id": "write_coherence",
    "scenario_name": "Write with KB context",
    "timestamp": "2026-03-26T14:30:00Z",
    "llm_profile": "local_thinking",
    "llm_model": "qwen3-8b",
    "project_dir": "bench/projects/lens_bench_..."
  },
  "steps": [
    {
      "step_id": "continue_unprompted",
      "command": ["write"],
      "description": "Continue without a prompt",
      "output": "Elena stepped beneath the canopy..."
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
