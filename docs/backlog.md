# Lens Backlog

- **Prompt assembly and retry architecture** audit (see below)
- **Addressing text sections from a tool call without line numbers**. Operators can point to places in a narrative node or a KB item (at a line resolution, not finder) by using a line-numnber-less diff-style selection: 
   1. Select target: narrative node or KB item
   2. Select start: provice **full verbatim line** you want to start your selection from (inclusive)
      - If this line is NOT UNIQUE in the document for any reason, add context lines _before or after_ to uniquely identify it (provide the minimum as a rule... extra doesn't hurt)
      - This is obviously very handy if the line you are targeting is empty, which is totally a valid selection
   3. If selecting a range, do the same for the last line; this is also inclusive, so a single-line range does not need a second selection
   4. Use a notation like `@@@start` or `@@@end` to signify the beginning or end, so if you wanted to select the last line of the doc, which happens to be empty, you would say `\n` as the target and `[@@@end` as the "lines after for context"
      - If you want to pre-pend or append, just select `@@@start` or `@@@end` directly... giving those as the range is a full replace, of course
   5. A resolver then takes target plus selections and resolves them into line numbers, or return an error if things are not found/not unique. This is used to select a section of document to replace, or a cursor position to add to (the content is another parameter). A tool call could have multiple selections and content, which are applied in turn.
- **`kb_patch` tool** allow operators to tool-patch a KB object’s body (different than “emit fenced kb blocks for human review.”) This is a straightfoward application of the above addressing of ranges plus content replacement
- **`collate` tool** uses a range selection on a node, provides a section slug, and calls collate; it can take a summary, or create one for you; this allows the AI to auto-compress its context as it goes, but in a purposeful way, as in "well, that topic is over, let's just remember the gist"  
   - This works on a **single** contiguous range on the **current node** only
   - Section summaries appear as **continuous blockquotes** (`>`); the tool contract should tell the model **not to split a contiguous quoted run** because that run is really matching a sub-node! This way collate targets stay structurally sane even before the operator’s own checks.
   - The collate tool does NOT colalte! It surfaces the request as a _suggestion_ to the user, which can just click on the UI accept (or change), which then _actually_ calls the operator. Actually calling collate would restructure the context and could be quite error-prone if the LLM keeps going.
- **Use `kb_patch` to remember**: whitelist objects/types that the AI can just update as it goes!
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
