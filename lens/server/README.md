# Lens API server

FastAPI server that hosts one or more Lens projects over HTTP.

## Starting the server

Run from a **project directory** (contains `lens.toml`) to serve that single project, or from a **parent directory** (no `lens.toml`) to auto-discover all immediate subdirectories that are Lens projects. The slug for each project is its directory name.

**`lens serve`** — build the frontend and serve the bundle:

- Runs `npm install && npm run build` if static assets are missing.
- Single URL (e.g. `http://127.0.0.1:8000`) for both API and frontend.
- No hot-reload; use for production or e2e.

**`lens dev`** — development with HMR:

- Starts the API server and the Vite dev server.
- Open **http://localhost:5173** for the frontend with hot module reload.
- Vite proxies all API paths to FastAPI.
- Requires Node.js and npm.

Both support `--host` and `--port` options.

## Routes

All project-specific routes are prefixed with `/{slug}`. Replace `{slug}` with the project directory name.

### Global

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Global liveness probe; returns `{"status": "ok"}`. No project context needed. |
| GET | `/projects` | List available projects: `[{"slug": "..."}, ...]`. |

### Status

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{slug}/stats` | Project stats: active narrative, cursor, pending transaction state, dataset, KB counts. `active_session_operator` is the session *currently open* over the cursor (see Operator detection below) — the UI gates session-close affordances (`play --end`, `chat --end`) on it. |
| GET | `/{slug}/explain` | Prompt composition at a cursor: every component with block, bytes, estimated tokens, share, and provenance, plus per-block and grand totals. Read-only — no transaction, no model call. |

**`GET /{slug}/explain` query parameters**

| Param | Default | Description |
|-------|---------|-------------|
| `address` | cursor | Node to report on (e.g. `/chapter-1`, `/@cursor`). |
| `line` | — | 1-based line; the current passage is reported as ending there. |
| `operator` | detected | Assemble as this operator instead of the one detected at the cursor. 400 if unknown. |
| `prompt` | — | Prompt text to include, as if passed to the operator. |
| `sort` | `order` | `order`, `size`, or `id` — ordering of components within each block. |
| `chars_per_token` | `4` | Divisor for the token estimate (1–32). |

**Operator detection.** With no `operator` param, the report assembles as the operator that would actually run at that node: an open session on any ancestor (`play`, `design`, `chat`, `advance`) owns it, otherwise the node's own unclosed annotation, otherwise the most recent *completed* narrating block (`write` plus the session operators — structural tags like `section` are skipped). The last rule matters because an inline turn closes as soon as it finishes, which is the state a report is almost always read in.

Both rules live in `lens/core/operator_detect.py`, shared with `/stats`. Note that they answer different questions: `detect_operator_name` (explain, and the modality report in stats) says *what would run here* and therefore honours a closed inline turn, while `detect_open_session_operator` (`stats.active_session_operator`) says *is a session still open* and returns `null` once it closes — a finished session must not keep offering to end itself.

Response: `{address, node, operator, line, blocks[], excluded[], totals{bytes, tokens, accounted_bytes, other_bytes, other_tokens, messages, message_bytes}, chars_per_token, active_modalities[], pinned_ids[], warnings[]}`. Each block carries `{id, label, role, bytes, tokens, percent, framing_bytes, framing_tokens, cache, components[]}`; each component carries `{id, kind, block, order, bytes, tokens, percent, provenance, provenance_kind, cache, detail}`. Provenance kinds: `node_pin`, `expansion`, `mention`, `rules_companion`, `module`, `modality`, `operator_pin`, `operator`, `narrative`.

**Everything reconciles.** `framing_bytes` / `framing_tokens` are what the block adds around its components (the `--- begin/end <title> ---` wrapper plus separators), so `block.bytes == Σ components.bytes + framing_bytes` and the same holds for tokens; `totals.bytes == Σ blocks.bytes + other_bytes` and `totals.tokens == Σ blocks.tokens + other_tokens`. A client can render a stacked bar from either unit without a leftover slice. Token counts are an estimate — every part is estimated independently and aggregates are sums of their parts, so the total is marginally higher than estimating the whole prompt in one pass; byte counts are exact.

The payload carries only machine values: `cache` is `prefix` / `volatile` (a heuristic until prompt caching lands), and each surface writes and localizes its own explanation of what that means — the API does not ship prose.

The UI consumes this route from `features/explain/` (context modal, opened by the cursor **context** button or `/structure-explain`). It renders blocks from the array rather than a fixed list — `conversation` replaces `current_passage` when the passage parses into turns — and recomputes shares in the displayed unit, since `percent` is byte-based.

### Narrative

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{slug}/narrative/narratives/active` | Switch the active narrative (`{"narrative": "<slug>"}`). |
| GET | `/{slug}/narrative/tree` | Recursive tree of narrative nodes (address, key, children). |
| GET | `/{slug}/narrative/node/{address}` | Node content by address. Returns `address`, `content`, `children`. 404 if not found. |

### Pinning

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{slug}/narrative/pin` | Pin KB ids, vars, operator params, or modality config on a node. `node` defaults to `/@cursor`. **KB:** `{"kind":"kb"` (optional), `"operation": "add"\|"remove"\|"block"\|"unblock", "ids": [...]}`. **Var:** `{"kind":"var", "operation": "set"\|"unset", "key": "...", "value": "..." }` (`value` required for `set`). **Param:** `{"kind":"param", "operation": "set"\|"unset", "scope": "global"\|"<slug>", "key": "...", "value": ... }` (`value` required for `set`). **Modality:** `{"kind":"modality", "operation": "set"\|"unset", "modality_id": "...", "key": "...", "value": ... }` (`value` required for `set`) — writes/clears one key in `modalities.<modality_id>` (see [configuration.md](../../docs/configuration.md#enabling-and-anchoring-front-matter); `key: "enabled"` is the on/off toggle, other keys are modality-specific, e.g. `media_attach`'s `anchor`). |

### Rewind

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{slug}/narrative/rewind` | Rewind the cursor to a node or line. Body: `{"address": "<address>", "line": <optional int>}`. |

### Knowledge base

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{slug}/kb/types` | List all KB object types. |
| GET | `/{slug}/kb/tags` | List unique tags, optionally filtered by `?type=` and `?prefix=`. |
| GET | `/{slug}/kb/items` | List KB items, optionally filtered by `?type=` and `?tags=`. |
| GET | `/{slug}/kb/item/{id}` | Fetch a single KB object. |
| PUT | `/{slug}/kb/item/{id}` | Save (overwrite) a KB object. Body: `{"content": "<markdown>"}`. |
| DELETE | `/{slug}/kb/item/{id}` | Delete a KB object. |
| POST | `/{slug}/kb/items` | Create a new KB object. Body: `{"id": "<id>", "content": "...", "use_template": false}`. |
| POST | `/{slug}/kb/copy` | Copy a KB object. Body: `{"source_id": "...", "target_id": "..."}`. |
| POST | `/{slug}/kb/rename` | Rename a KB object. Body: `{"old_id": "...", "new_id": "..."}`. |
| PATCH | `/{slug}/kb/item/{id}/tags` | Modify tags on a KB object. Body: `{"add": [...], "remove": [...]}`. |
| GET | `/{slug}/kb/template/{type}` | Get the template for a KB object type. |
| PUT | `/{slug}/kb/template/{type}` | Set the template for a KB object type. Body: `{"content": "..."}`. |
| POST | `/{slug}/kb/with-tag` | Query KB objects by tag. Body: `{"tags": [...], "expand": false, "recurse": null, "same_type_only": false}`. |

The mutating routes above are **direct user edits**: they use `session.new_direct_edit_storage()`, which stages only the files it writes and leaves any pending operator preview unstaged and discardable (see "Direct user edits" in [docs/design.md](../../docs/design.md#git-backed-storage)). `POST /kb/edit` (below) is AI-generated content and deliberately stays a normal reviewable transaction. A direct edit that touches a file the pending transaction already changed is *not* staged — it merges into that transaction instead.

Direct-edit routes build their own `KnowledgeStore`, so any route that mutates tags must call `session.kb.evict_tag_cache()` afterwards to keep the shared store coherent.

### Transaction

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{slug}/staged` | Full diff of currently staged changes. |
| POST | `/{slug}/rollback` | Discard all unstaged changes. |
| POST | `/{slug}/commit` | Stage the current pending transaction. |
| POST | `/{slug}/checkpoint` | Commit staged changes and push to remote. Body: `{"message": "...", "push": true}` (both optional). |
| POST | `/{slug}/refresh` | Fetch and fast-forward from upstream. |

### Operator streaming

`POST /{slug}/operator/*` endpoints stream progress as SSE (`text/event-stream`). Responses include workflow step events (`type: "workflow"`) for multi-step operators (generate → auto-compress, summarize → remember, etc.).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{slug}/stream/cancel` | Stop the active stream. Completed workflow steps remain in the pending transaction; use rollback to discard the preview. |
| POST | `/{slug}/stream/workflow/action` | Retry or skip a paused workflow step. Body: `{"step_id": "<id>", "action": "retry"\|"skip"}`. |

Closing the browser tab or dropping the SSE connection auto-cancels the active stream (same semantics as explicit cancel). One stream at a time per project (409 if busy).

## Architecture

The server is a thin adapter over `lens/core/`. Routes validate input, call core functions, and translate domain exceptions to HTTP errors. No business logic lives in routes.

- `server/` imports only from `core/`, never from `cli/`.
- `core/` is synchronous. Routes call blocking core functions directly or via `run_in_threadpool` when needed.
- All domain exceptions must be caught in routes and mapped to HTTP 400/500.
- Per-project stream locks are stored in `app.state.stream_locks` (dict keyed by slug), lazily created.

## Authentication

Authentication is handled entirely by the reverse proxy (Caddy). FastAPI trusts all incoming requests as authenticated — no token validation, no session management. If Caddy is removed, the server must not be exposed to the public internet.

## UI testing (Playwright)

End-to-end browser tests live under the repo root in `e2e/tests/test_browser.py`. They use **pytest-playwright** against a real Chromium instance. Session fixtures in `e2e/conftest.py` spin up a throwaway Lens project, fake LLM, and an in-process uvicorn server unless `LENS_DEV_SERVER_URL` is set.

### Prerequisites

```bash
poetry install --with e2e
playwright install chromium
poe build-ui   # if static assets are missing
```

### Running

```bash
poe test-e2e                        # full e2e suite
pytest e2e/tests/test_browser.py -v # browser tests only
```

### External server

Point tests at an already-running server by setting `LENS_DEV_SERVER_URL`. Use the SPA origin (Vite URL for `lens dev`, API URL for `lens serve`):

```bash
LENS_DEV_SERVER_URL=http://127.0.0.1:8000 pytest e2e/tests/test_browser.py -v
```

### Sandbox (browse the e2e fixture project)

```bash
poe build-ui    # if needed
poe e2e-sandbox
```

Opens a throwaway project (narrative slug `story`, Lorem ipsum content) in the browser. Ctrl+C tears it down.
