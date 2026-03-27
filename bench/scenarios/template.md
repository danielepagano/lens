# Scenario title

One-paragraph description of what this scenario tests and why it matters.

```config
datasets:
```

**Prompt keys exercised:** `operator.key_name`

## Setup

`setup_bench.py` only creates an empty project with narrative `default`. Explain
what state this scenario builds and list the commands to get there:

```bash
lens kb add type.key "..."
lens pin add type.key
lens commit

lens write "Opening passage that establishes the narrative state."
lens commit
```

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
