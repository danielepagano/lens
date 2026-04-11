# Lens Backlog

- **Prompt assembly and retry architecture** audit (see below)
- **Librarian (background compression + memory)**: first background operator — a pre-pass that runs before each unbounded creative call, quietly compressing cold material in the cursor node and (when applicable) writing durable facts to KB. The goal is that a user can "just chat" or "just play" indefinitely without context bloat. Reuses the existing `collate` operator and the existing chat-memory prompt + `kb_patch` tool — no new primitives.
   - **Scope: unbounded operators only.** Runs before `write`, `chat` (inside a session), and `play` (inside a session). Does **not** run before `design` (would break `kb extract`), `edit`, `collate`, `section`, or any one-shot. `advance` — TBD, depends on whether it streams into a growing node. The decision is at operator-dispatch time: if the main op is unbounded and the cursor node is large enough, the librarian gets a chance to fire.
   - **Compression pass (always available).** Picks at most one contiguous, cold, safe-to-lose range and emits a regular `collate` call. Structural rules are inherited from `collate` (no splitting front matter, annotations, or existing summary blockquotes; no unclosed annotations in range). Cold-region bias: the candidate must lie entirely within the first K% of the node — the cursor (at the end) never gets touched.
   - **Scribe pass (conditional, free when available).** Runs only when the active session already declares memory ids — today that's `chat` with `--memory`. Uses the existing chat memory prompt + `kb_patch` tool, scoped to those ids only. `play` gets it automatically if/when it grows a memory concept; `design` keeps its own front-grooming pattern (`advance`/`design`) untouched. Compression works standalone — memory is a bolt-on, not a prerequisite.
   - **Trigger (heuristic, all AND'd).** Cursor node size delta since last run ≥ `size_delta_bytes`; at least `min_turns_between` turns since last run; a valid cold-region candidate exists. If any check fails, exit cheaply — no LLM call, no cost. State lives in the cursor node's front matter (`librarian_last_bytes`, `librarian_last_turn`) so rewinds and manual collates naturally re-baseline the trigger.
   - **Config** (`[librarian]` in `lens.toml`, all optional with conservative defaults): `enabled = true`, `size_delta_bytes`, `min_turns_between`, `cold_region_ratio`, `llm` (defaults to the project's default LLM; can point at a cheaper one). Per-narrative override allowed. A single boolean flip disables it entirely.
   - **Transaction model.** Librarian runs before the main op assembles context, so the main op sees the compressed node. Its writes go through `Storage` under a distinct owner; when the main op makes its first write, the librarian's changes are auto-staged (existing Storage semantics). Consequence: **`lens rollback` on the main op does NOT undo the librarian's compression** — bookkeeping persists across creative rollback. If the librarian itself errors, log a warning and fall through to the main op unchanged; never block creative work on bookkeeping.
   - **UX.** Silent on success, one terse log line (`librarian: compressed /chapter-1 lines 8–34 into #prelude`). Visible in `lens stats -v` as part of the staged diff. No modal, no UI artifact — it's plumbing.
   - **Precedent.** This is the first background operator, so the pattern (pre-op hook, config block, trigger state in front matter, silent-on-success + never-blocking + bookkeeping-survives-rollback) should be set up with future background ops in mind. Avoid hard-coding "librarian"-specific plumbing where a general pre-op background hook would do.
- **Public Release Readiness**
   - License
   - Clean up documentation
      - Actual user manual for playing RPGs
   - Remove hard-coding of usage of gitlab/fly, make modular/CI-friendly
      - Remove reliance on specific env vars
   - Better "no desktop" usage
      - Better init tooling/docs
      - Streamline project creation/management
      - Streamline campaign bootstrapping
      - Ensure manual editing is solid
      - Some way to have a hook in a project to Lens to trigger deploy automatically
   - Improve maintainability
      - Explicit contribution guidelines?
      - Git hook/CI/merge rules
      - Clean up of UI in particular: smaller modules, cleaner interfaces
   - Use and tweak usability over time
   - When ready
      - Force push to clean up history
      - Make repo public
      - Immediately add main branch protection


## Prompt assembly and retry architecture audit

**Context:** `--retry "feedback"` was implemented using multi-turn messages (assistant: previous output, user: feedback + rewrite directive). This exposed a deeper inconsistency worth fixing properly.

### The problem

Two incompatible patterns coexist:

- **Edit** (`_do_retry_mutation`): single-turn. The original selection is embedded inline in the instruction with an explicit label (`PASSAGE TO REVISE — replace this and only this`). The system prompt says "your output is inserted verbatim in place of the passage." Scope is unambiguous even without multi-turn context.
- **Write / play / design / advance** (`_do_retry`): multi-turn. Previous output as `assistant` turn, feedback + "Rewrite from scratch" as `user` turn. But the system prompts for these operators say nothing about replacement scope, so the model may treat the conversation as additive rather than substitutive.

### What to audit and decide

1. **Replacement clarity in system prompts.** Write/play/advance/design system prompts currently frame the model as a writer/designer/GM — they say nothing about what happens on retry. Either (a) add a conditional reminder when `retry=True` is in play, or (b) accept that multi-turn with an explicit user directive is sufficient, and verify empirically.

2. **Multi-turn vs. inline for both.** Decide on one pattern:
   - *Inline (edit's way):* embed previous output inside the user turn with a label. Simpler, unambiguous, but loses the naturalness of conversational refinement.
   - *Multi-turn (feedback's way):* keep assistant+user turns, but also update edit's retry to use the same pattern (currently edit retry on feedback just replaces the prompt — it never shows the model what it previously wrote).
   The multi-turn pattern is better aligned with how instruction-tuned models are trained (they see correction loops in training data). Inline is safer for models without strong multi-turn fine-tuning.

3. **Prompt cache friendliness.** `assemble_prompt` returns `[system, user]` — a stable prefix if system prompt + knowledge + passage don't change. Appending `[assistant, user]` turns is fine for cache: the prefix is still intact and cacheable; only the suffix varies. The current implementation is actually cache-friendly by accident. Worth verifying this is intentional and that no call site rebuilds messages in a way that shifts the cache boundary.

4. **`assemble_prompt` and pinned_ids.** `CrawlResult` carries `pinned_ids` but `assemble_prompt` doesn't use them — callers reconstruct them from params. Worth checking whether knowledge assembly order is deterministic (cache-stable) across calls with the same KB state.

5. **Consistency check:** `_do_retry` (inline operators) and `_do_retry_mutation` (edit) should be brought to parity on the feedback path. Right now only inline operators capture previous content for feedback; edit ignores it and just replaces the prompt.

### References
- `lens/core/operator.py`: `_do_retry`, `_do_retry_mutation`, `build_feedback_messages`, `extract_annotation_content`
- `lens/core/operators/edit.py`: `EditOperator`
- `lens/prompts/default.toml`: `edit.system`, `write.system`, `shared.retry_feedback_template`
- `lens/core/context.py`: `assemble_prompt`, `CrawlResult`
