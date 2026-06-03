# E2E regression fixtures

Reusable project shapes for the LLM-driven regression plan (1524eaf0 → HEAD). Python setup lives in [`helpers.py`](helpers.py); shell scripts support manual runs.

Overview of all testing tooling: **[docs/testing.md](../../docs/testing.md)**.

## Programmatic setup (pytest)

```python
from e2e.fixtures.helpers import setup_remember_section, setup_auto_compress_low_threshold
from lens.testing.fake_llm import FakeLLMServer

with FakeLLMServer() as llm:
    session = setup_remember_section(Path("/tmp/proj"), llm.base_url)
```

## Manual sandbox (human checklist SH-*)

```bash
poe build-ui
TMP=$(mktemp -d)
export PROJECT="$TMP"

# Pick a fixture:
bash e2e/fixtures/remember_section/setup.sh   # after lens init in PROJECT — see below

# Or use extended sandbox (initializes project + fixture):
poe e2e-sandbox --fixture remember_section
```

For a full manual project without sandbox helper:

```bash
cd "$PROJECT"
# lens.toml + git: use setup_test_project or copy from a pytest temp dir
export PROJECT
bash e2e/fixtures/remember_section/setup.sh
lens serve --port 8765
# Open http://127.0.0.1:8765/#<slug>/story
```

## Fixtures

| Directory | Cases | Notes |
|-----------|-------|-------|
| `auto_compress_low_threshold` | AC-01–03, AW-03, SH-04 | Low `[compress]` thresholds via `helpers.setup_auto_compress_low_threshold` |
| `remember_section` | AC-05, AW-02/04, SH-02–03 | Section child + remember.smoke pin |
| `workflow_write_long` | SH-01 | Long root prose (helpers only) |
| `rpg_play_pins` | AC-13, AC-15, SH-05 | `datasets = [rpg, testing]` + pins |
| `advance_minimal` | AC-16, B-03 | Port of `bench/scenarios/advance_fronts_setup.sh` |

## Bench (B-01–B-07)

Quality scenarios remain under [`bench/scenarios/`](../../bench/scenarios/). Run per [`bench/agent.md`](../../bench/agent.md):

```bash
PROJECT=$(python bench/tools/setup_bench.py --profile local_thinking --scenario bench/scenarios/remember_section.md)
export PROJECT
bash bench/scenarios/remember_section_setup.sh
# … scenario steps …
```
