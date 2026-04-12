# Lens Backlog

- **Move chat memory system to `remember` system.** Today `chat` uses a special `--memory` parameter to call `kb_patch` on specific objects as it goes... that's slow, and probably ineffective. What we need to do is remember things _when we may lose them_, so during summarization. Thus, the output of summarization would be both the summary (reads nicely in the story for continuity) and KB changes (the nitty-gritty details we need).
   - **KB Object Selection** it's important we keep this targeted like chat does, but also it cannot be in an operator annotation however many nodes away. The memorization needs to be _both targeted and faceted_:
      - We introduce `remember.*` KB object that tells us "how to remember from a certain point of view". This could be anything, like `remember.alice` for "what Alice wants to remember", `remember.loot` to track RPG loot, `remember.encounter` for "what kind of things we want to remember after an encounter", etc. These object may or may not care which objects you are updating; they are facets, not targets. There is no particular template for these. 
      - We then tag the objects we want to update with `kb_patch` with one or more dot-tags of `remember.*`. If the objects we taggd are in the pinned set during a summary, the remember tag will trigger the memory system and also provide its prompt, which is designed to be modular with a baseline plus the `remember` objects contents. So for example `lore.alice` could have a core memories section and we tag it with `remember.core-memories` so that the LLM looks for core memories specifically, then looks at the target object and creates/alters that section based on the instructions. 
         - We can also say that, given `remember.X` if there is also a `X._template` object, that is included in the prompt, so that the memory system knows what goes into these objects and what the format it.
         - We technically don't _need_ `remember` objects, we can just say that if one is missing the entire instruction is in the tag key, e.g. `remember.kills` attached to a kill log with some examples hardly needs more details! The AI would just be told to "use this object to remember kills".
   - We need to enable thinking mode to go through each remember-tagged object and think if and how what we are summarizing affects it, then create a proper patch. This can get slow/complicated if we over-do it.
   - **Tool-call logs** for the `kb_patch` calls made during a compress are appended at the end of the content being summarized (i.e. the new node): they are wasted tokens in a higher level node, but tool call visibility is always good!
- **`compress` operator**: allows an LLM to call `collate`: it selects a single contiguous range on the current node and delegates to `collate` to move it into a new child section. The framing is *"topic is over, let's just remember the gist"* — compression is a purposeful act, not a mechanical rollup. Because `collate` makes summaries, we also automatically use the `remember` system, so now we have the LLM performing two dimensions of compressions at once!
   - How compress derives `collate` parameters:
      - **`start_line` and `end_line`**: uses the same reference-line-with-context selection that `kb_patch` uses (anchor lines quoted with surrounding context). This is key to the tool contract and how LLM-picked ranges are reliable at the text level: this mechanism must be kept spec-aligned with `kb_patch` so the two share validation/resolution code, and also share the same prompt components.
         - **Structural rules are phrased in what the LLM can see.** The LLM cannot see annotations, so the tool contract cannot say "don't split annotations"; that would be nonsense to a model that doesn't see them. The only structural boundary the LLM actually perceives is **existing section summaries**, which appear as a sequence of <!-- section:id -->, a h3 header (`###`), and one run of blockquotes (`>`). Those cannot be split (they correspond 1:1 to sub-nodes, and collate cannot "split" a sub-node). The contract tells the LLM, in visible terms: "your range must not cut through a section: comment + heading + blockquote summary block; keep them whole." That is sufficient to stay consistent with `collate`'s real structural rules without the LLM needing to know annotations exist. The operator then re-validates the resolved range against the real node text before executing, and errors cleanly on bad range, split annotation, etc.
      - `id`: this is decided by the LLM as it reasons on what to collate
      - `summary_guide`: the LLM could encouraged to use this to focus the summary based on the wider context
      - `address`: this is a cursor operator, so always the current node
      - `pin`, `unpin`, `llm`, and `reasoning`: optionally passed through via configuration or directly by the user to `compress`.
   - **Optional `prompt`** parameter: when called manually, the user can just tell the LLM what they want to compress, e.g. "dinner", "dessert course", "initial skirmish before cave". Otherwise the LLM needs to work out if anything merits a collate (this is its main job normally)
   - **Automated Compression.** Because `compress` actually needs no parameters, we can use a heuristic to call it automatically. To do this, we need state and rules. 
      - **Node Size** is important here, so we need to work out if we want to count bytes (cheap+fast), words (simple+slower), estimated tokens (words+math), actual tokens (LLM-dependent, can be slow/tricky/unknown). Let's gloss this over for now and just refer to "size".
      - **State** tracks when we last called `compress`, so we don't do it too often. So when we call `compress` on a node (manually or otherwise), its front matter records `compress.last_size` which is the size of the node after our last compress (minus the annotation itself, if it was added after). This is the baseline of the change in size we may want to compress. Rewinds and manual collates naturally shrink the node, so current size could be smaller than last, which is good to know!
      - **Size Rules** tell us when to trigger automated compression. We want to compress so that the current node can be appended to indefinitely while increasingly compressing the past, so nodes need _size thresholds_; we can just use t-shirt sizes (`sm,m,l,xl`) with the values depending on our size unit, model context window, and user preferences about cost etc. The sizes should mean:
         - `sm`: the smallest sub-node we should try to make when collating; we wouldn't collate something this small further
         - `m`: average sub-node size, lean current node size
         - `l`: max size we'd normally like for a node, but we can live with it
         - `xl`: we need to do something about making this smaller
      - **Auto-selection of range.** The LLM needs to decide what to select for collation. The main idea is to find cohesive chunks that make a cogent summary, and heavily favor older content; in fact, we can probably make a rule that the newest 15-20% of a node is off-limits, the selection could even fail if we try. We should give it min and ideal ranges for sections we want, and also give an `aggressiveness` level:
         - `low`: only collate if we have have a fairly clean target to collate, like a clean transition or an aside in the narrative; keep new node around `sm` size; higher change of doing nothing than something
         - `medium`: we should try to collate something if possible; still aim for a clean topic of `sm-m` size; more likely to act than not, but can still pass
         - `high`: we MUST collate something: take roughly the earliest half of the node, find a somewhat reasonable spot, and collate it
      - **Triggering.** We must be in a `section`, `play`, or `chat` node, then we  look at node size and size delta. 
         - `<m` size node: compression not helpful, don't bother
         - `m-l`: we can compress down with `low` aggressiveness, but only if we never done it, or delta between current and last size is at larger than `sm`.
         - `l-xl`: we can compress down with `medium` aggressiveness, but with same delta check as above
         - `>xl`: how did we get here? Compress down with `high` aggressiveness right now!
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
