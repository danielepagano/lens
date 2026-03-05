# LLM Architecture: Command Tools and the Agentic Loop

## Summary

Lens now supports two distinct classes of LLM tool calls with clearly separated
semantics and performance profiles.

| Class | Examples | Effect | LLM layer |
|---|---|---|---|
| **Operator tools** | write, play, section | Exits LLM layer; hands off to another operator | Terminates |
| **Command tools** | kb_get, kb_with_tag | Executes inline; conversation continues | Stays open |

---

## API Compatibility

Both OpenRouter and LM Studio expose identical OpenAI-compatible SSE streaming
at `/v1/chat/completions`. Tool calls arrive as `delta.tool_calls[i].function.{name,arguments}`
fragments that must be accumulated across chunks. No abstraction layer or
native clients are needed — the existing `httpx`-based SSE client in
`core/llm.py` handles both providers correctly.

One minor quirk: some LM Studio builds omit `"type": "function"` from the
first tool-call chunk. This is handled defensively in `_stream_once`.

### Why not OpenRouter's native extensions or LM Studio's `/api/v1/`?

Both providers offer non-standard extensions, but:
1. The OpenAI-compatible format already covers every feature Lens needs.
2. Staying on the standard format keeps the single `httpx` client working
   with any future provider.

---

## Architecture

### `core/llm.py` — Two-layer streaming

**`_stream_once(messages, cfg, verbose, *, stop_sequences, tools, cancel_event)`**

Executes one HTTP streaming request. Yields preview `StreamEvent` objects
during generation and exactly one `StreamEvent(final=...)` at the end.
Handles tool-call accumulation, fold logic for parallel operator tool calls,
and `encode_ai_secrets`. Does not install a SIGINT handler.

**`generate_stream(messages, project_root, *, ..., command_tool_handlers)`**

Outer loop. Installs the SIGINT handler once, then calls `_stream_once` in a
loop of up to `_MAX_COMMAND_TOOL_ITERATIONS` (10):

```
loop:
  call _stream_once(working_messages)
  forward all preview events to caller
  receive FinalPayload

  if interrupted:
    yield final with interrupted=True; raise KeyboardInterrupt

  if tool_call.name in command_tool_handlers:
    execute handler(args, project_root) → result string
    append assistant message + tool message to working_messages
    continue loop          ← NO prompt rebuild; O(tool_result_tokens) cost

  else:  # operator tool or no tool
    yield final to caller  ← caller dispatches operator tool as before
    break
```

The original `messages` list is never mutated. `working_messages` is a
local copy that grows by two messages per command tool iteration.

### `core/command_tools.py` — Command tool registry

```python
@dataclass(slots=True)
class CommandToolDef:
    description: str
    parameters: dict[str, Any]  # JSON Schema

CommandToolFn = Callable[[dict[str, Any], Path], Awaitable[str]]
```

`register_command_tool(name, tool_def, fn)` populates `_REGISTRY` at import
time. `get_command_registry()` returns a snapshot.

Two tools registered:

| Name | Core call | Returns |
|---|---|---|
| `kb_get` | `KnowledgeStore.get_objects_with_links(ids)` | Formatted KB objects |
| `kb_with_tag` | `KnowledgeStore.get_ids_with_all_tags` / `traverse_by_dot_tags` + `get_objects` | IDs + formatted KB objects |

`kb_add` is **intentionally excluded**: KB mutations belong only to planning
operators (design, advance) whose outputs go through `lens kb extract`. This
keeps narrative writes predictable.

### `core/operator.py` — Wiring

`Operator` gains one new ClassVar:

```python
use_command_tools: ClassVar[bool] = True
```

`_do_fresh_inline` builds `command_handlers` when `cls.use_command_tools` is
`True`, adds command tool definitions to `tools_payload`, and passes them to
`generate_stream`. The rest of `_do_fresh_inline` is unchanged — operator tool
dispatch (`_dispatch_tool_call`) continues to work exactly as before.

---

## Operator Policy

| Operator | `use_command_tools` | Rationale |
|---|---|---|
| `write` | `True` (default) | Can benefit from inline KB lookups |
| `section` | `True` (default) | Same |
| `edit` | `True` (default) | Same |
| `play` | **`False`** | Speed over knowledge; `@mention` pre-processor handles explicit lookups; thinking is the enemy of fun |
| `design` | `True` (default) | Core workflow: think → look up → propose |

---

## `design` Operator

A planning-mode operator. Produces KB proposals as fenced `kb` blocks rather
than narrative prose. The user runs `lens kb extract` to apply them.

**System prompt instructs the LLM to:**
1. Think before proposing (reason about connections and implications)
2. Check what already exists via `kb_get` / `kb_with_tag` before writing
3. Output proposals exclusively as fenced `kb` blocks in `lens kb extract` format
4. Use `<!-- ai:secret: ... -->` for hidden information (auto-encoded by the platform)
5. Follow tagging and linking conventions from object templates

**Available in all projects** (no `limited_to_datasets` restriction).

**Does not register as an operator tool** — design sessions are always
user-initiated and are too long and context-heavy to chain from `play`.

---

## Message History Cost

Each command tool round-trip adds:
- One assistant message (tool_calls, content may be empty)
- One tool message (the result string)

For typical KB lookups (1–3 objects), this is 200–800 tokens per iteration —
well within budget. The system prompt and narrative context are **not**
re-serialised; only the incremental messages are new.

If future context overflow becomes a concern (deep design sessions with many
lookups), old tool messages can be summarised or pruned in `working_messages`
before passing to `_stream_once`. This is not implemented today.

---

## Token Cost Analysis (Play vs Design)

```
play (use_command_tools=False):
  1 LLM call
  Cost: prompt_tokens + completion_tokens
  Latency: one network round-trip

design (use_command_tools=True, 2 kb_get calls):
  3 LLM calls
  Cost: prompt_tokens
      + (completion_1 + tool_result_1 + completion_2 + tool_result_2
         + completion_3 + completion_tokens_3)
  Latency: three network round-trips
  Benefit: proposals grounded in actual KB state, no hallucinated object IDs
```

The extra cost in design is acceptable because design sessions are
infrequent, high-value, and correctness matters more than speed.

---

## Future Work

- **Thinking mode**: Planning operators (design, advance, encounter) should
  support extended thinking via `reasoning: { effort: "high" }` (OpenRouter)
  or equivalent. Add an optional `thinking_budget` field to `[[llm]]` in
  `lens.toml` that, when set, appends the provider-appropriate parameter to
  the payload in `_stream_once`.

- **`advance` operator**: Similar to `design`. Loads fronts, crawls narrative,
  generates a luck roll, and proposes front updates as `kb` blocks + state log
  entry. Heavy `kb_with_tag` usage (find all active fronts + linked objects).

- **`encounter` operator**: Planning sub-node. Uses `kb_with_tag` to find
  matching stat blocks; proposes encounter structure.

- **Context pruning**: If `len(working_messages) > threshold`, summarise older
  tool results in the loop before calling `_stream_once`.
