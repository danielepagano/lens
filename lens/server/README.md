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
| POST | `/refresh` | Fetch and fast-forward to upstream, or with `{"reset": true}` reset hard to upstream and remove untracked files. |

### Operator streaming

`POST /operator/*` endpoints stream progress as SSE (`text/event-stream`). `POST /stream/cancel` aborts the active stream and rolls back partial narrative changes. Only one stream may run at a time (`409` if busy), enforced via `app.state.stream_lock`.

All routes use the same `ProjectSession` (project/dataset and active narrative) fixed when the server starts.

## Architecture

The server is a thin adapter over `lens/core/`. Routes validate input, call core functions, and translate domain exceptions to HTTP errors. No business logic lives in routes.

- `server/` imports only from `core/`, never from `cli/`.
- `core/` is synchronous. Routes call blocking core functions directly or via `run_in_threadpool` when needed. Do not make core code async.
- All domain exceptions must be caught in routes and mapped to HTTP 400/500. Core code must not call `sys.exit()` or `print()`.
- One SSE stream at a time is enforced via `app.state.stream_lock` (shared by operator routes).

## Authentication

Authentication is handled entirely by the reverse proxy (Caddy). FastAPI trusts all incoming requests as authenticated — it performs no token validation, no session management, and no auth headers. If Caddy is removed, the server must not be exposed to the public internet.

Caddy is configured to:
- Terminate HTTPS
- Enforce HTTP Basic Authentication
- Forward authenticated traffic to FastAPI (localhost only)
- Pass through SSE (`text/event-stream`) without buffering (`X-Accel-Buffering: no`)

## UI testing (Playwright)

End-to-end browser tests live under the repo root in `e2e/tests/test_browser.py`. They use **pytest-playwright** against a real Chromium instance. The same session fixtures as the rest of `e2e/` apply (`e2e/conftest.py`): a throwaway Lens project, fake LLM, and an in-process uvicorn server on a free port, unless you point tests at an already-running server.

### Prerequisites

1. **Install the e2e dependency group** (provides `pytest-playwright`; the `page` fixture comes from this plugin):

   ```bash
   poetry install --with e2e
   ```

2. **Install the Chromium browser binary** (one-time per machine):

   ```bash
   playwright install chromium
   ```

3. **Build the frontend** so FastAPI can serve `lens/server/static/` (or run `poe check`, which runs `build-ui` before `test-e2e`):

   ```bash
   poe build-ui
   ```

### Running the tests

```bash
# Full e2e suite (API + browser; browser tests skip if Chromium or static assets are missing)
poe test-e2e

# Browser tests only
pytest e2e/tests/test_browser.py -v
```

### External server (optional)

To drive the UI against a server you already have running (e.g. while iterating on the frontend), set `LENS_DEV_SERVER_URL` to the **same origin the browser should load** — the URL that serves the SPA and can reach the API:

- **`lens serve`** (or production-style single port): use that URL, e.g. `http://127.0.0.1:8000`.
- **`poe dev`**: use the **Vite** URL (`http://localhost:5173` by default), which proxies API routes to uvicorn — not only the API port alone, or the test will not load the bundled UI.

```bash
LENS_DEV_SERVER_URL=http://127.0.0.1:8000 pytest e2e/tests/test_browser.py -v
```

With `LENS_DEV_SERVER_URL` set, the session skips creating a temp project and fake LLM; tests run against whatever project that server was started with.

### Browse what Playwright sees (e2e fixture project)

Pytest’s **auto mode** (no `LENS_DEV_SERVER_URL`) builds a **throwaway** temp project: narrative slug **`story`**, opening text from the **fake LLM** (Lorem ipsum), `testing` dataset. That is **not** your `test-lens` tree.

To point **your browser** at that same data without running pytest:

```bash
poe build-ui    # if static assets are missing
poe e2e-sandbox
```

Open the printed URL — usually `http://127.0.0.1:<port>/#story`. That stack matches what `live_server_url` uses in `e2e/conftest.py` (fake LLM + `setup_test_project` + uvicorn). Ctrl+C tears down the temp directory.

Optional: `poe e2e-sandbox -- --port 8123` to pin a port.

### Your own project (e.g. `test-lens`)

To make Playwright hit **the same server and repo** you use in the browser:

1. **Start the app from your content repo** (so `lens.toml` and `narrative/` are that project):

   ```bash
   cd /Users/daniele/dev/test-lens   # or your project path
   lens serve                        # note host:port (often http://127.0.0.1:8000); builds UI if needed
   ```

   Build the static bundle first if you rely on a fresh `lens/server/static` (from the **Lens** repo: `poe build-ui`, or your usual workflow).

   Or **`lens dev`**: use the **Vite** URL printed in the log (often `http://localhost:5173`), not only the API port.

2. **From the Lens tool repo** (where `pytest` / `e2e/` live), point tests at that origin:

   ```bash
   cd /path/to/lens   # this repository
   poetry install --with e2e
   LENS_DEV_SERVER_URL=http://127.0.0.1:8000 pytest e2e/tests/test_browser.py -v
   ```

   Use the same scheme/host/port you open in the browser (`localhost` vs `127.0.0.1` must match what you use manually if cookies/storage matter).

3. **What still differs from your manual flow**

   - **`test_edit_replace_after_line_pick_shows_inline_codemirror`** navigates to **`#story`** and builds the command with **line-picker clicks** + `--replace`, not a **single pasted line** like  
     `/edit /amy-story/amy-morning 16 18 --replace`.  
     That is a **different** parse/interaction path than typing everything in one go.
   - To get **closer** to your one-line command, either:
     - Use **Playwright Codegen** against your URL and record typing/pasting that exact string, or  
     - Run a small script that sets the CLI value and fires the same events Svelte sees, e.g. after `goto` to the right hash (`#amy-story/amy-morning`):

       ```js
       const t = document.querySelector('[data-testid="cli-input"]');
       t.value = '/edit /amy-story/amy-morning 16 18 --replace';
       t.dispatchEvent(new InputEvent('input', { bubbles: true }));
       ```

       then focus the textarea and press Enter (or dispatch a `keydown` for Enter the way the app expects).

   - **`#` in the URL** must match the narrative **address** you care about (`#story` vs `#amy-story/amy-morning`); the bundled test assumes the throwaway project’s root slug.

4. **Debug**

   - `PWDEBUG=1 pytest e2e/tests/test_browser.py::TestBrowser::test_edit_replace_after_line_pick_shows_inline_codemirror -v` opens the Playwright inspector (step through, compare with manual).

### Selectors and what to assert

Prefer **`data-testid`** hooks already used in the app (examples: `top-bar`, `tree-browser`, `cli-input`, `markdown-view`, `line-picker`, `streaming-preview`, `inline-edit-view`). That keeps tests stable when class names or layout change.

Example behaviour covered today: while the CLI is filling an `edit` command and the active slot is a **line** (`valueType: line` in `lens/server/ui/src/commands/operators.ts`), the main content switches from rendered markdown (`.markdown-html-root` inside `markdown-view`) to a **read-only CodeMirror** source view (`data-testid="line-picker"`, pickable lines use `.cm-line.cm-linepick-pickable`). A regression test for that lives in `test_edit_line_slot_shows_line_picker_not_markdown_preview`.
