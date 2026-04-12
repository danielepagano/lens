# Lens Backlog

- **Automated Compression.** Because `compress` actually needs no parameters, we can use a heuristic to call it automatically. To do this, we need state and rules. 
   - **Node Size** is important here, so we need to work out if we want to count bytes (cheap+fast), words (simple+slower), estimated tokens (words+math), actual tokens (LLM-dependent, can be slow/tricky/unknown). Let's gloss this over for now and just refer to "size".
   - **State** tracks when we last called `compress`, so we don't do it too often. So when we call `compress` on a node (manually or otherwise), its front matter records `compress.last_size` which is the size of the node after our last compress (minus the annotation itself, if it was added after). This is the baseline of the change in size we may want to compress. Rewinds and manual collates naturally shrink the node, so current size could be smaller than last, which is good to know!
   - **Size Rules** tell us when to trigger automated compression. We want to compress so that the current node can be appended to indefinitely while increasingly compressing the past, so nodes need _size thresholds_; we can just use t-shirt sizes (`sm,m,l,xl`) with the values depending on our size unit, model context window, and user preferences about cost etc. The sizes should mean:
      - `sm`: the smallest sub-node we should try to make when collating; we wouldn't collate something this small further
      - `m`: average sub-node size, lean current node size
      - `l`: max size we'd normally like for a node, but we can live with it
      - `xl`: we need to do something about making this smaller
   - **Auto-selection of range.** The LLM needs to decide what to select for collation. The main idea is to find cohesive chunks that make a cogent summary, and heavily favor older content; in fact, we can probably make a rule that the newest 15-20% of a node is off-limits, the selection could even fail if we try. We should give it min and ideal ranges for sections we want, and also give an `aggressiveness` level (control the prompt used):
      - `low`: only collate if we have have a fairly clean target to collate, like a clean transition or an aside in the narrative; keep new node around `sm` size; higher change of doing nothing than something
      - `medium`: we should try to collate something if possible; still aim for a clean topic of `sm-m` size; more likely to act than not, but can still pass
      - `high`: we MUST collate something: take roughly the earliest half of the node, find a somewhat reasonable spot, and collate it
   - **Triggering.** We must be in a `section`, `play`, or `chat` node, then we look at node size and size delta. 
      - `<m` size node: compression not helpful, don't bother
      - `m-l`: we can compress down with `low` aggressiveness, but only if we never done it, or delta between current and last size is at larger than `sm`.
      - `l-xl`: we can compress down with `medium` aggressiveness, but with same delta check as above
      - `>xl`: how did we get here? Compress down with `high` aggressiveness right now!
   - **Semi-auto.** Having the above, we can now make the `prompt` parameter of `compress` optional: if not provided, our system can just go through the automatic flow of range and aggressiveneness auto-selection.
   - **Enabling.** We can configure `[auto-compress] = off | review | auto` in `lens.toml` (per-narrative override allowed).
      - `off`: manual only.
      - `review`: the main operator is **not** run. Instead the user is prompted *"compression due, run compress instead?"*. If yes, compress runs and the main op is abandoned (user re-runs it next turn, now against the compressed node). If no, the main op proceeds.
      - `auto`: compress is run after the main op (we don't want to change context from under the user).
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
- **Prompt assembly and retry architecture** audit (see below)

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
