# Lens API server

FastAPI server that exposes the current Lens project (or dataset) over HTTP.

## Starting the server

Run from a directory inside a Lens project (a repo that contains `lens.toml`):

**`lens serve`** — build the frontend and serve the bundle:

- Runs `npm install && npm run build` if static assets are missing.
- Single URL (e.g. `http://127.0.0.1:8000`) for both API and frontend.
- No hot-reload; use for production or e2e.

**`lens dev`** — development with HMR:

- Starts the API server and the Vite dev server.
- Open **http://localhost:5173** for the frontend with hot module reload.
- Vite proxies `/health`, `/stats`, `/narrative/` and all other API paths to FastAPI.
- Requires Node.js and npm.

Both support `--host` and `--port` options. The server uses the project (or dataset) rooted at the nearest `lens.toml` above the current working directory.

- **Project mode**: Full API. Narrative tree and node content are available; `active_narrative` and cursor come from `lens.toml`.
- **Dataset mode**: If `lens.toml` declares a `[dataset]`, the server still runs but narrative routes return empty or 404 (no narrative nodes in a dataset).

## Routes

### Status

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness; returns `{"status": "ok"}`. |
| GET | `/stats` | Project stats: active narrative, cursor, pending transaction state, dataset, KB counts. Includes inline transaction diff when `has_pending` is true. |

### Narrative

| Method | Path | Description |
|--------|------|-------------|
| POST | `/narrative/narratives/active` | Switch the active narrative (`{"narrative": "<slug>"}`). Narrative list and active come from `/stats`. |
| GET | `/narrative/tree` | Recursive tree of narrative nodes (address, key, children). Empty in dataset mode. |
| GET | `/narrative/node/{address}` | Node content by address (e.g. `chapter-1/scene-2`). Returns `address`, `content`, `children`. 404 in dataset mode or if node not found. |

### Pinning

| Method | Path | Description |
|--------|------|-------------|
| POST | `/narrative/pin` | Add, remove, block, or unblock KB pins on a node. Body: `{"operation": "add"\|"remove"\|"block"\|"unblock", "ids": [...], "node": "<address>"}`. `node` defaults to `/@cursor`. |

### Rewind

| Method | Path | Description |
|--------|------|-------------|
| POST | `/narrative/rewind` | Rewind the cursor to a node or line, deleting everything after. Body: `{"address": "<address>", "line": <optional int>}`. |

### Knowledge base

| Method | Path | Description |
|--------|------|-------------|
| GET | `/kb/types` | List all KB object types. |
| GET | `/kb/tags` | List unique tags, optionally filtered by `?type=` and `?prefix=`. |
| GET | `/kb/items` | List KB items, optionally filtered by `?type=` and `?tags=` (comma-separated, supports group syntax). |
| GET | `/kb/item/{id}` | Fetch a single KB object: `id`, `type`, `content`, `tags`. |
| PUT | `/kb/item/{id}` | Save (overwrite) a KB object. Body: `{"content": "<markdown>"}`. |
| DELETE | `/kb/item/{id}` | Delete a KB object. |
| POST | `/kb/items` | Create a new KB object. Body: `{"id": "<id>", "content": "...", "use_template": false}`. |
| POST | `/kb/copy` | Copy a KB object. Body: `{"source_id": "...", "target_id": "..."}`. |
| POST | `/kb/rename` | Rename a KB object. Body: `{"old_id": "...", "new_id": "..."}`. |
| PATCH | `/kb/item/{id}/tags` | Modify tags on a KB object. Body: `{"add": [...], "remove": [...]}`. |
| GET | `/kb/template/{type}` | Get the template for a KB object type. |
| PUT | `/kb/template/{type}` | Set the template for a KB object type. Body: `{"content": "..."}`. |
| POST | `/kb/with-tag` | Query KB objects by tag with optional recursion. Body: `{"tags": [...], "expand": false, "recurse": null, "same_type_only": false}`. |

### Transaction

| Method | Path | Description |
|--------|------|-------------|
| GET | `/staged` | Full diff of currently staged (not yet committed) changes. |
| POST | `/rollback` | Discard all unstaged changes (pending transaction). |
| POST | `/commit` | Stage the current pending transaction (moves unstaged → staged). |
| POST | `/checkpoint` | Commit all staged changes and push to the remote repo. Body: `{"message": "...", "push": true}` (both optional). |

### CLI streaming

| Method | Path | Description |
|--------|------|-------------|
| POST | `/cli/run` | Run a lens CLI command as a subprocess, streaming stdout/stderr as SSE. Body: `{"command": "<subcommand>", "payload": "<args string>"}`. Only allowlisted commands accepted; only one run at a time (409 if busy). |
| POST | `/cli/cancel` | Terminate the currently running CLI subprocess. |

#### CLI SSE events

Each event is a JSON object on the `data:` field:

| `type` | Meaning |
|--------|---------|
| `out` | A line of stdout (`text` field) |
| `err` | A line of stderr (`text` field) |
| `done` | Process exited (`exit_code` field) |

All routes use the same `ProjectSession` (project/dataset and active narrative) fixed when the server starts.

## Architecture

The server is a thin adapter over `lens/core/`. Routes validate input, call core functions, and translate domain exceptions to HTTP errors. No business logic lives in routes.

- `server/` imports only from `core/`, never from `cli/`.
- `core/` is synchronous. Routes call blocking core functions directly or via `run_in_threadpool` when needed. Do not make core code async.
- All domain exceptions must be caught in routes and mapped to HTTP 400/500. Core code must not call `sys.exit()` or `print()`.
- One CLI subprocess at a time is enforced via `app.state.cli_run`.

## Authentication

Authentication is handled entirely by the reverse proxy (Caddy). FastAPI trusts all incoming requests as authenticated — it performs no token validation, no session management, and no auth headers. If Caddy is removed, the server must not be exposed to the public internet.

Caddy is configured to:
- Terminate HTTPS
- Enforce HTTP Basic Authentication
- Forward authenticated traffic to FastAPI (localhost only)
- Pass through SSE (`text/event-stream`) without buffering (`X-Accel-Buffering: no`)
