# Remember at section close (smoke)

End-to-end smoke test for the **remember** pass that runs after **`lens section
--end`**: pinned `lore.testbench` carries `remember.smoke`, optional facet
instructions (`remember.smoke`) plus `smoke._template` shape hints, the child
section states a **durable beverage fact** about Rex, then the summary + remember
LLM calls should leave either a **`kb_patch` tool-call fence** (and/or
`<!-- remember:` notes) on the closed section’s child file** and/or an updated
**`lore.testbench`** body.

Uses **project-local KB only** (no extra datasets beyond `testing` still bundled
by `setup_bench.py`).

```config
datasets:
```

**Prompt keys exercised:** `session.summary_system`,
`session.summary_instruction_template`, `remember.system`,
`remember.instruction_template`

## Setup

Builds `remember.smoke` (facet instructions), `smoke._template`, `lore.testbench`
(tagged `remember.smoke`), pins `lore.testbench` at the narrative root, opens
section `remember-smoke`, and **replaces** the child body with a short scripted
beat (fixed text — do not use `lens write` for that body).

**Implementation:** `bench/scenarios/remember_section_setup.sh`. From the repo
root:

```bash
export PROJECT
bash bench/scenarios/remember_section_setup.sh
```

## Steps

### `section_end_remember`

Closes the section: **summary** is written into the parent; **remember** may call
`kb_patch` on `lore.testbench` only, then any model/tool trace is appended to the
child node.

```bash
lens section --end --reasoning low
```

After the run, create or refresh the report (`report.py init` / `merge` — see
`bench/agent.md`).

**Quick smoke checks (human or agent):**

- `lens check` still succeeds.
- `narrative/default/remember-smoke.md` contains a fenced `tool-call` block
  (triple-backtick fence as emitted by Lens) and/or a `<!-- remember:` block
  after the run **or** the file grew only with summary
  activity in the parent — at minimum the command must not error.
- `lens kb get lore.testbench` — look for a **bench note** mentioning **lime tea**
  (or equivalent capture of the scripted fact). If the model added only a
  “no preference” style line, score fidelity lower but the pipeline still ran.

## Evaluation criteria

Score the **combined outcome** (parent summary + KB durability + child trace) on
a 1–5 scale:

1. **Pipeline** — `lens section --end` completes without operator/LLM hard
   failure; `lens check` passes
2. **KB patch target** — `lore.testbench` reflects the scripted **lime tea**
   preference (or clearly documents that nothing applied)
3. **Remember trace** — Child file shows tool-call markdown and/or bounded
   `<!-- remember:` commentary rather than raw narrative leakage
4. **Summary quality** — Parent recap is shorter than the child, keeps Rex +
   the expo / tea beat, no invented subplot
5. **Instruction hygiene** — No `kb_patch` attempts against ids other than
   `lore.testbench` (rejections would appear in tool output)

## Prompt iteration guidance

**Focus keys:** `remember.system`, `remember.instruction_template`

**Goal:** Reliable, selective `kb_patch` after summarization without spamming
unpinned KB objects; clear tool visibility on the child node.

**Anti-patterns to watch for:**

- **Silent skip** — no remember output and KB unchanged despite an obvious
  scripted fact (may indicate crawl/pin/tag misconfiguration)
- **Wrong target** — patches to unrelated ids (should be blocked; watch for
  error strings in tool fences)
- **Hallucinated beverages** — summary or KB invents drinks not in the child text
