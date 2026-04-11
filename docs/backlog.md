# Lens Backlog

- **Prompt assembly and retry architecture** audit (see below)
- **Compress operator + opt-in automation**: an LLM-driven operator that selects a single cold contiguous range on the current node and delegates to `collate` to move it into a new child section, optionally also emitting `kb_patch` calls when the node's context declares memory ids. The framing is *"topic is over, let's just remember the gist"* — compression is a purposeful act, not a mechanical rollup. Exposed as `lens compress` on the CLI and "structure-compress" in the UI. Normal operator: normal `--llm`/`--pin`/`--unpin`, normal transaction, normal rollback. A thin automation layer on top lets unbounded operators (`write`, `chat`, `play`) either prompt the user to compress first or do it silently.
   - **Range selection uses the `kb_patch` mechanism.** The operator's LLM picks its range using the same reference-line-with-context selection that `kb_patch` uses — anchor lines quoted with surrounding context, not raw line numbers. This is the core of the tool contract; it is the only reason LLM-picked ranges are reliable at the text level, and it must be kept spec-aligned with `kb_patch` so the two share validation/resolution code.
   - **Current node only.** Compression is restricted to the cursor node because that is the only node whose full text the LLM sees — ancestor nodes appear to the model only as summaries in the assembled context, so the LLM cannot meaningfully select a range in them. Same visibility boundary that already governs `write`. `lens compress` therefore takes no address argument.
   - **Structural rules are phrased in what the LLM can see.** The LLM **cannot see annotations at all** — not `[section:id]: #`, not `[write ...]: #`, not markdown comments. So the tool contract cannot say "don't split annotations"; that would be nonsense to a model that doesn't see them. The only structural boundary the LLM actually perceives is **existing section summaries** inside the current node, which appear as an `<h3>` header followed by a continuous blockquote (`>`) body — one such block per closed sub-section. Those cannot be split (they correspond 1:1 to sub-nodes, and collate cannot "split" a sub-node). The contract tells the LLM, in visible terms: *"your range must not cut through a heading + blockquote summary block; keep them whole."* That is sufficient to stay consistent with `collate`'s real structural rules without the LLM needing to know annotations exist. The operator then re-validates the resolved range against the real node text (including annotations and front matter) before executing, and errors cleanly on bad range, split annotation, slug collision, etc.
   - **Optional summary guidance (LLM-supplied and/or user-supplied).** The LLM's selection output may include an optional guidance blurb for the summary pass (*"emphasize the foreshadowing in the dialog"*). This is especially useful in `chat` mode, where the *character itself* can phrase what they'd want kept from the scene — the model is literally the voice deciding what's worth remembering. Users can also pass `--summary-guide` on the CLI, exactly like `lens collate` today.
   - **Memory refactor (same change, not deferred).** Move chat's memory system prompt and the `kb_patch` tool out of the `chat` operator and into `compress`. Chat keeps `--memory` for carrying ids into context as pins; it stops writing KB itself. Consolidating all narrative-context KB writes through `compress` gives the same memory mechanism to any session that declares memory ids (today `chat`; later potentially `play` or other), and removes `chat`'s write-to-KB side-channel. Tool-call logs for the `kb_patch` calls made during a compress are appended inside the newly-created sub-node itself, so the compression's full work product (summary + remembered facts) is one browsable artifact.
   - **State tracking in front matter, not annotations.** The cursor node's front matter records `compress.last_bytes` / `compress.last_turn`. No claim annotation is needed — compress delegates to `collate`, which writes its own section annotation as normal. Rewinds and manual collates naturally re-baseline the stats since they shrink the node, so the trigger doesn't fire spuriously after the user has already shed bulk another way.
   - **Automation layer.** `[compress] automatic = off | review | auto` in `lens.toml` (per-narrative override allowed). Before an unbounded operator (`write`, `chat` in session, `play` in session) runs, a pre-op hook checks whether compression is due on the cursor node against conservative thresholds (size delta since last run + turns since last run are the obvious axes; exact defaults TBD). Behavior:
      - `off` (default until tuned): never auto-triggers. Manual only.
      - `review`: the main op is **not** run. Instead the user is prompted *"compression due on /chapter-1 — run compress instead?"*. If yes, compress runs and the main op is abandoned (user re-runs it next turn, now against the compressed node). If no, the main op proceeds.
      - `auto`: compress runs first, then the main op proceeds against the compressed node in its own transaction.
   - **Scope of automation.** `write`, `chat` (in session), `play` (in session). Never `design` (would break `kb extract`), never bounded ops (`edit`, `collate`, `section`), never one-shots. `advance` is out of scope — it's a specialized `design`-shaped operator.
   - **Config.** `[compress]` section in `lens.toml`: `automatic = off` plus the automation thresholds. No dedicated `llm` field — `--llm` works on `lens compress` like any other operator; users pick cheap/fast themselves if they want to.
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
