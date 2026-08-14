# Scenario title

One-paragraph description of what this scenario tests and why it matters.

```config
datasets:
```

The `testing` dataset is added to every bench project by default, because most
scenarios use its cast. Add `include_testing: false` to this block to leave it
out — needed when it would interfere, e.g. it registers `rules.skirmish` as a
`play` module, which competes with a real dataset's modules for the same trigger.

**Prompt keys exercised:** `operator.key_name`

## Setup

`setup_bench.py` only creates an empty project with narrative `default`. Explain
what state this scenario builds.

For anything beyond a couple of lines, add a checked-in
`bench/scenarios/<scenario>_setup.sh` (see `advance_fronts_setup.sh`) and point
to it from here. From the repo root: `export PROJECT` and
`bash bench/scenarios/<scenario>_setup.sh`.

Small scenarios may keep inline fenced `bash` in this file instead.

## Steps

### `step_id`

What this step tests and what good output looks like.

```bash
lens write "instruction"
```

## Evaluation criteria

Score each step's output on a 1–5 scale:

1. **Criterion name** — What to look for, described concretely enough to score
2. **Another criterion** — ...

## Prompt iteration guidance

**Focus key:** `operator.key_name`

**Goal:** What "better" means for this scenario.

**Anti-patterns to watch for:**

- **Pattern name** — concrete description of bad output
