# Frontend — Architecture Guide

Svelte + Vite single-page app. Mobile-first. Served as a static bundle from the FastAPI server in production.

## Stack

- **Svelte** — component structure and reactivity
- **Vite** — dev server and bundler
- **Pico.css** — baseline styling only
- **CodeMirror 6** — markdown editor
- **markdown-it** — markdown rendering
- **Native `EventSource`** — SSE (only via `services/sse.ts`)
- **Native `fetch`** — HTTP (only via `services/api.ts`)

Do not introduce additional frameworks, UI libraries, CSS frameworks, or state management libraries.

## Svelte and repo-local validation

Treat these commands (from `lens/server/ui`) as the source of truth for the frontend:

- `npm run check` (`svelte-check`)
- `npm run lint` (ESLint + `eslint-plugin-svelte`)
- `npm run build` (Vite compile)

At the repo root, `poe lint`, `poe check-svelte`, and `poe check` wrap the same checks.

If an external Svelte helper disagrees with those results, trust the repo-local output rather than rewriting code to satisfy the helper alone.

When you touch a `.svelte` file, keep it in runes-era style (`$props`, `$state`, `$derived`, `$effect`, DOM event props like `onclick`). Do not mix legacy syntax (`export let`, `on:`, `$:`) into the same component. Use `<svelte:options runes={false} />` only as a rare, justified escape hatch.

## File structure

```
src/
  main.ts
  App.svelte
  layout/          # TopBar, BottomBar, MainLayout — fixed; not redefined by features
  features/        # Feature-scoped components (editor, viewer, tree, kb, transaction, cli)
  services/
    api.ts         # All fetch calls
    sse.ts         # All EventSource usage
  stores/
    session.ts
    ui.ts
    document.ts
  utils/
```

## Hard constraints

1. **No component exceeds ~300 lines.**
2. **CodeMirror is configured only in the editor component** — nowhere else.
3. **Network logic lives only in `services/`** — no component instantiates `EventSource` or calls `fetch` directly.
4. **Global state lives only in `stores/`** — no component-local state duplicates global state.
5. **Layout is fixed in `MainLayout.svelte`** — feature code must not redefine layout hierarchy.
6. **No inline `innerHTML` manipulation** outside `MarkdownView.svelte`.
7. **No feature reaches into another feature's internals.**
8. **Always use narrative address paths** (e.g. `/chapter-1`) for node identification — never internal IDs.

## Authentication

Authentication is handled by Caddy at the proxy layer. The frontend:

- Does not implement login UI.
- Does not attach `Authorization` headers.
- Does not manage sessions or tokens.
- Assumes: if the page loaded, the user is authenticated.
- On 401: treat as fatal and let the browser trigger the HTTP Basic re-authentication challenge. Do not handle 401 programmatically.

SSE works transparently behind Caddy Basic Auth — the browser includes credentials automatically with `EventSource` requests.

## State model

Stores are flat and minimal:

- `document.ts` — current node address, raw markdown, rendered HTML, transaction state, cursor position, unstaged range markers
- `ui.ts` — active panel, editor/read mode, modal visibility
- `session.ts` — session-level state

No nested reactive trees. No state management library.

## Transaction visibility

Unstaged changes must be visually distinct from committed content. The UI must provide explicit controls:

- **Discard** — rollback unstaged changes (`POST /rollback`)
- **Save** — stage the pending transaction (`POST /commit`)
- **Checkpoint** — push all staged changes to the remote repo (`POST /checkpoint`)

Never expose git terminology to the user. Use "Checkpoint", "Save", "Discard" — not "Push", "Commit", "Rollback".

## Refresh behaviour

On page load or refresh, fetch the current project state (active narrative, cursor, transaction status) from the backend. Do not rely on client-side routing, localStorage, or any cached state to reconstruct context.

## SSE streaming flow

```
Operator invoked via POST /operator/* (SSE)
→ backend returns text/event-stream
→ client parses SSE (api.ts + sse.ts)
→ StreamPanel / CliOutputPanel show tokens or tool output from stores
→ On "done" event, UI refreshes state from backend
```

Streaming must not mutate DOM directly. Only update stores; let Svelte bindings handle DOM.

## Testing

Use Playwright for integration tests:
- Load document, enter edit mode, select lines, trigger operator, validate streaming, validate commit state.
- No unit tests for trivial components; focus on integration behaviour.
