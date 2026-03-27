# Lens Functional Benchmark

Functional quality benchmarks for Lens operators against real LLMs.

## Quick start

```bash
# 1. Create an empty benchmark project (active narrative: default; scenario Setup adds KB/prose)
PROJECT=$(python bench/tools/setup_bench.py --profile local_thinking --scenario bench/scenarios/write_coherence.md)

# 2. cd into the project directory (default: bench/projects/lens_bench_*)
cd "$PROJECT"

# Optional: verify lens.toml, keys, datasets, and narrative (run after cd)
lens check
# If this fails, you stop and report to user

# 3. Run the scenario (read the scenario file + the relevant script under bench/scripts/). If the scenario has a bench/scenarios/<name>_setup.sh, run it from the repo root with PROJECT exported (see bench/agent.md).

# 4. Create report JSON + HTML (init prints the JSON path — use that path for merge/sync; optional: -o bench/reports/<label>.json)
python bench/tools/report.py init \
  --scenario bench/scenarios/write_coherence.md \
  --profile local_thinking \
  --project-dir "$PROJECT"

# 5. Complete the report — same JSON basename as step 4 (…json → …html next to it)
python bench/tools/report.py merge bench/reports/<your_report>.json < patch.json
# or: edit JSON, then: python bench/tools/report.py sync bench/reports/<your_report>.json

# Optional: verify shape + scenario step IDs
python bench/tools/report.py validate bench/reports/<your_report>.json --scenario bench/scenarios/write_coherence.md

# 6. Open the paired HTML
open bench/reports/<your_report>.html
```

Replace `<your_report>` with the JSON filename from step 4 (`init` output or your `-o` value). The HTML is the same basename with `.html`.

**Agents:** read `bench/agent.md` first — a run starts there; it requires a **script**, **scenario**, and **LLM profile** (plus optional user instructions); **run `lens` from a shell** after `cd` into the project (env + network), and **`lens check`** must succeed; then **create the report**. Empty `steps` / `evaluation` is not a finished run.

## Three use cases

1. **Develop & baseline** — `bench/scripts/baseline.md`
2. **Compare LLMs** — `bench/scripts/compare.md`
3. **Iterative prompt engineering** — `bench/scripts/iterate.md`

Read `bench/agent.md` for shared mechanics, then the script you need.

## Directory structure

```
bench/
  agent.md                Agent run: inputs, shell + lens check, outputs, reports
  README.md
  tools/
    setup_bench.py        Setup script: empty project + LLM profile; narrative `default`
    report.py             Reports: init, merge, sync, render, compare
    report_template.html  Self-contained HTML template
  scripts/
    baseline.md           Use case 1: develop & baseline
    compare.md            Use case 2: compare LLMs
    iterate.md            Use case 3: iterative prompt engineering
  llm_profiles/           LLM configuration presets (TOML)
  scenarios/              Test scenario definitions (Markdown)
    template.md           Blank scenario template
  projects/               Default throwaway Lens projects (gitignored)
  reports/                Output directory (gitignored)
```

## LLM profiles

TOML files in `llm_profiles/` configure which LLM to use:

```toml
[llm]
base_url = "http://127.0.0.1:1234/v1"
model = "qwen3-8b"
temperature = 0.7
timeout_seconds = 300
# api_key_env = "XAI_API_KEY"   # for cloud providers
```

## Scenarios

Markdown files in `scenarios/`. Each has:

- **Title + description** — what the scenario tests
- **````config` block** — machine-readable datasets (the only part Python parses)
- **Setup** — CLI commands to build narrative state
- **Steps** — benchmark operations to evaluate
- **Evaluation criteria** — scoring rubric (1–5)
- **Prompt iteration guidance** — focus key, goal, anti-patterns

See `scenarios/template.md` for a blank starting point.

## Replay mechanics

Lens provides built-in replay for cheap iteration (no project rebuild needed):

| Command | Effect |
|---------|--------|
| `lens write --retry` | Discard current output, regenerate (same or new prompt) |
| `lens rollback` | Discard pending transaction entirely |
| `lens rewind /@cursor` | Clean up open tail at cursor |
| `lens rewind /` | Rewind to narrative root |
| `lens prompt set <key> "..."` | Override a prompt at project level |
| `lens prompt clear <key>` | Restore the default prompt |

Details and the full agent contract are in `bench/agent.md`.
