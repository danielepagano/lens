# Lens Functional Benchmark

Functional quality benchmarks for Lens operators against real LLMs.

## Quick start

```bash
# 1. Create a benchmark project (requires a local LLM server on :1234)
python bench/tools/setup_bench.py --profile local_thinking --scenario bench/scenarios/write_coherence.md

# 2. cd into the printed project directory
cd /tmp/lens_bench_...

# 3. Run the scenario (read the scenario file + the relevant use-case prompt)

# 4. Render the report
python bench/tools/report.py render bench/reports/your_report.json
open bench/reports/your_report.html
```

## Three use cases

1. **Develop & baseline** — `prompts/baseline.md`
2. **Compare LLMs** — `prompts/compare.md`
3. **Iterative prompt engineering** — `prompts/iterate.md`

Read `prompts/core.md` first (shared mechanics), then the use-case prompt you need.

## Directory structure

```
bench/
  README.md
  tools/
    setup_bench.py        Setup script: creates project with real LLM
    report.py             JSON -> HTML renderer (render, compare)
    report_template.html  Self-contained HTML template
  prompts/
    core.md               Shared mechanics (setup, replay, scoring, reports)
    baseline.md           Use case 1: develop & baseline
    compare.md            Use case 2: compare LLMs
    iterate.md            Use case 3: iterative prompt engineering
  llm_profiles/           LLM configuration presets (TOML)
  scenarios/              Test scenario definitions (Markdown)
    template.md           Blank scenario template
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
- **`~~~config` block** — machine-readable datasets (the only part Python parses)
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
