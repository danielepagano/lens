# Edit line-range quality

Tests the **edit** operator on a **deterministic** passage: the weak region is
inserted with `lens edit … --replace`, not `lens write`, so evaluators know the
exact source text and line range.

Uses **`location.registry`** from the bundled `testing` dataset (Charter Registry
Hall — vinegar, wax, clerks) as pinned context. The node includes prose **before and
after** the weak paragraph so the edit has voice anchors; the benchmark **edit
instruction** asks for concrete physical dread without telling the model to
re-describe the hall (that would fight `edit.system`’s “do not restate CURRENT
PASSAGE”).

```config
datasets:
```

**Prompt keys exercised:** `edit.system`, `edit.instruction_template`

## Setup

Replace the scaffolded root node with the prepared passage (pins are embedded in
the front matter) and commit.

**Implementation:** `bench/scenarios/edit_quality_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/edit_quality_setup.sh
```

## Steps

### `edit_rewrite`

The Martine paragraph is the line starting with `Martine stood` (line number
varies if the file changes — resolve it with `grep`).

```bash
M=$(grep -n '^Martine stood' narrative/default/_node.md | head -1 | cut -d: -f1)
lens edit / "$M" "$M" "Rewrite only the paragraph marked PASSAGE TO REVISE. Third person. Keep Martine at the counter, the deal-book, the clerk, and the brass edge tapping. Replace the vague worry sentences with concrete physical detail—hands, breath, small movements—so her reluctance to sign is clear without emotion labels (do not use nervous, worried, uncertain, afraid, or similar). Do not restate, summarize, or echo the opening hall paragraph or the lines after this paragraph."
```

## Evaluation criteria

Score the **staged edit proposal** on a 1–5 scale:

1. **Instruction following** — Substantially removes abstract emotion labeling as the main crutch; body language and concrete detail carry the unease; does not echo the neighboring paragraphs
2. **Preservation** — Still Martine at the counter with the deal-book and the clerk’s tapping; same moment in time
3. **Prose quality** — More varied rhythm and specificity than the original; not a synonym swap
4. **Consistency** — Matches tone of the opening hall paragraph and the closing lines
5. **Scope** — Does not expand into a new subplot or change who is present; does not repeat surrounding paragraphs (check for duplicate opening)

## Prompt iteration guidance

**Focus key:** `edit.system`

**Goal:** Edits that read like a strong line edit under constraint — same beat,
stronger execution.

**Anti-patterns to watch for:**

- **Thesaurus mode** — “apprehensive,” “on edge,” still no scene
- **Overwriting** — flashbacks, new characters, or a full arc in one paragraph
- **Voice break** — ornate or clinical where neighbors are plain
- **Fact drift** — clerk becomes magistrate, deal becomes marriage, etc.
- **Context echo** — restating the opening hall paragraph or the lines after Martine
