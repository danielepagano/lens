# Lens Backlog

- **Prompt assembly and retry architecture** audit (see below)
- **Compress operator + opt-in automation**: promote compression to a first-class operator (`lens compress`, "structure-compress" in the UI) instead of hiding it behind a background hook. It's a normal operator with normal `--llm`/`--pin`/`--unpin` options, a normal transaction (normal rollback), and no special config beyond a `[compress]` section for its triggers. Automation is a thin layer on top that either reviews or auto-runs compress before unbounded operators.
   - **Manual form.** `lens compress [ADDRESS]` (default: cursor node). Selects one cold contiguous range under `collate`'s structural rules (no splitting front matter/annotations/summary blockquotes; cursor region off-limits), delegates the actual move to `collate`, and generates the summary. If the target node's context declares memory ids, it also runs a scribe pass and emits `kb_patch` scoped to only those ids. Tool-call logs for the memory patches are appended inside the newly-created subsection itself, so the compression's full work product (summary + remembered facts) is one browsable artifact. State lives in the target node's front matter (`compress.last_bytes`, `compress.last_turn`) — not an annotation.
   - **Memory refactor (same change, not deferred).** Move the chat memory system prompt and the `kb_patch` tool out of the `chat` operator and into `compress`. Chat keeps `--memory` for carrying ids into context as pins; it no longer writes KB itself. Consolidating all KB writes from narrative context through `compress` means the same memory mechanism works for any session type that declares memory ids, and `chat` stops being the only operator with a write-to-KB side-channel.
   - **Automation layer.** `[compress] automatic = off | review | auto` in `lens.toml` (per-narrative override allowed). Before an unbounded operator (`write`, `chat` in session, `play` in session) runs, a pre-op hook checks whether compression is due on the cursor node (size delta ≥ `size_delta_bytes`, at least `min_turns_between` turns since last run, a valid candidate exists). Behavior:
      - `off` (default): never auto-triggers. Manual only.
      - `review`: the main op is **not** run. Instead the user is prompted *"compression due on /chapter-1, run compress instead?"*. If yes, compress runs and the main op is abandoned (the user re-runs it next turn, now against the compressed node). If no, the main op proceeds.
      - `auto`: compress runs silently first, then the main op proceeds against the compressed node in its own transaction.
   - **Scope of automation.** `write`, `chat` (in session), `play` (in session). Never `design` (breaks `kb extract`), never bounded ops (`edit`, `collate`, `section`), never one-shots. `advance` is out of scope — it's a specialized design-shaped operator.
   - **Config.** `[compress]` section in `lens.toml` with conservative defaults: `size_delta_bytes`, `min_turns_between`, `cold_region_ratio`, `automatic = off`. No dedicated `llm` field — `--llm` works like any other operator; users can pick cheap/fast themselves.
   - **Why this shape.** Compress is not plumbing; it's a user-facing operator that happens to be reusable by an opt-in pre-op hook. Rollback is normal (`lens rollback` on compress undoes it). Review mode turns an automatic action into an informed opt-in at the exact moment it matters. Memory moves to where KB writes belong. No new abstractions except the thin automation hook.
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
