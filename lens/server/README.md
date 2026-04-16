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
| GET | `/{slug}/stats` | Project stats: active narrative, cursor, pending transaction state, dataset, KB counts. |

### Narrative

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{slug}/narrative/narratives/active` | Switch the active narrative (`{"narrative": "<slug>"}`). |
| GET | `/{slug}/narrative/tree` | Recursive tree of narrative nodes (address, key, children). |
| GET | `/{slug}/narrative/node/{address}` | Node content by address. Returns `address`, `content`, `children`. 404 if not found. |

### Pinning

| Method | Path | Description |
|--------|------|-------------|
| POST | `/{slug}/narrative/pin` | Add, remove, block, or unblock KB pins on a node. Body: `{"operation": "add"\|"remove"\|"block"\|"unblock", "ids": [...], "node": "<address>"}`. `node` defaults to `/@cursor`. |

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

### Transaction

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{slug}/staged` | Full diff of currently staged changes. |
| POST | `/{slug}/rollback` | Discard all unstaged changes. |
| POST | `/{slug}/commit` | Stage the current pending transaction. |
| POST | `/{slug}/checkpoint` | Commit staged changes and push to remote. Body: `{"message": "...", "push": true}` (both optional). |
| POST | `/{slug}/refresh` | Fetch and fast-forward from upstream. |

### Operator streaming

`POST /{slug}/operator/*` endpoints stream progress as SSE (`text/event-stream`). `POST /{slug}/stream/cancel` aborts the active stream. One stream at a time per project (409 if busy).

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
