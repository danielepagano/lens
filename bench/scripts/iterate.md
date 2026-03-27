# Use Case: Iterative Prompt Engineering

Improve an operator's output quality by mutating its prompt, re-running, and
measuring the difference — all without rebuilding the project.

Prerequisite: read `bench/agent.md` for setup, replay mechanics, and scoring.

## Steps

### 1. Setup (once)

Create the project and run the scenario's setup commands. You only do this
once — iteration happens without re-running setup.

### 2. Read the active prompt

```bash
lens prompt get write.system
```

This prints the full prompt text and its source layer (builtin, pack, or
project). The scenario's **focus key** tells you which prompt to target.

### 3. Run and evaluate baseline

Run the scenario's steps, score against criteria. Note:
- Which criteria scored lowest
- Which anti-patterns from the scenario appeared in the output

### 4. Iterate

**You do not need to re-run setup.** Use replay mechanics:

#### Retry (cheapest — same state, new generation)

```bash
# Sample variability with the same prompt:
lens write --retry
lens write --retry

# Test a prompt change:
lens prompt set write.system "Your improved prompt here..."
lens write --retry
```

Use `--retry` to re-generate without changing narrative state. Multiple
retries with the same prompt measure variance.

#### Rollback (undo pending transaction)

```bash
lens rollback
lens write "same instruction"
```

Use when you want a completely fresh run of the current step.

#### Rewind (go back further)

```bash
lens rewind /@cursor       # clean up open tail
lens rewind /              # back to narrative root
```

Use when you need to undo committed steps and re-run from earlier.

### 5. Record each iteration

For each prompt change, capture:
- **What** you changed and **why** (your hypothesis)
- **Method**: retry, rollback, or rewind
- **Scores before and after**
- **Whether you kept the change**

### 6. Keep or revert

```bash
# Keep:
lens commit

# Revert:
lens prompt clear write.system
lens write --retry
```

### 7. Produce the iteration report

Create or update the report JSON and HTML as in `bench/agent.md`: use
`report.py init` when you start a report, then **`merge`** (preferred) or edit JSON and **`render`** / **`sync`** after each change so HTML never lags. The report JSON includes an `iterations` array:

```json
{
  "iteration": 1,
  "prompt_key": "write.system",
  "prompt_before": "You are a creative...",
  "prompt_after": "You are a creative... (modified)",
  "change_description": "Added natural KB integration instruction",
  "method": "retry",
  "samples": 2,
  "scores_before": { "average": 3.8 },
  "scores_after": { "average": 4.2 },
  "delta": 0.4,
  "kept": true
}
```

## Practical tips

- **Start with `--retry`** — only rollback/rewind when you need different
  narrative state.
- **Multiple retries = variance estimate.** If scores vary widely with the
  same prompt, the prompt is underspecified.
- **Read the anti-patterns** — they tell you what bad output looks like, which
  is often more actionable than the criteria alone.
- **One change at a time.** Changing multiple keys simultaneously makes it
  impossible to attribute improvements.
- **The prompt is not the only lever.** If output is poor despite a good
  prompt, check whether KB entries or pins provide enough context.
