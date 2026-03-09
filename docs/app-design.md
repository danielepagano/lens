# Lens Frontend Architecture Design

## 1. Purpose

The Lens frontend is a mobile-first, single-user web client for interacting with a FastAPI backend.

It must:

* Render markdown documents.
* Edit markdown with line-aware controls.
* Execute operators and stream responses via SSE.
* Navigate narrative nodes via a tree browser.
* Display transaction state (staged / unstaged).
* Allow pinning and simple object search.
* Remain predictable and maintainable when code is generated or modified by an LLM.

It must NOT:

* Contain business logic for Lens.
* Duplicate backend state logic.
* Smell like git.
* Become a general-purpose IDE.
* Introduce unnecessary architectural surface area.

This is a structured UI shell over an existing system.

---

# 2. Stack

## Runtime

* Svelte (component structure + reactivity)
* Vite (dev server + bundler)
* Pico.css (baseline styling)
* CodeMirror 6 (editor)
* markdown-it (markdown rendering)
* Native EventSource (SSE)
* Native Fetch API
* Caddy-based basic HTTP auth

Optional but recommended:

* Playwright (e2e tests)

No state management library.
No routing framework.
No UI component libraries.
No CSS frameworks beyond Pico.

---

# 3. Architectural Principles

### 3.1 Single Responsibility Boundaries

* Backend owns truth.
* Frontend renders and invokes.
* Editor is isolated.
* SSE handling is centralized.
* Authentication is isolated.

### 3.2 Constrained Component Model

Rules:

1. No component may exceed ~300 lines.
2. CodeMirror may only be configured in one file.
3. Network logic lives only in `services/`.
4. Global state lives only in `stores/`.
5. Layout structure is fixed and must not be redefined by feature code.
6. No inline `innerHTML` manipulation outside the markdown renderer.

---

# 4. File Structure

```
src/
  main.ts
  App.svelte

  layout/
    TopBar.svelte
    BottomBar.svelte
    MainLayout.svelte

  features/
    editor/
      MarkdownEditor.svelte
    viewer/
      MarkdownView.svelte
    tree/
      TreeBrowser.svelte
    ..etc

  services/
    api.ts
    sse.ts
    auth.ts

  stores/
    session.ts
    ui.ts
    document.ts

  utils/
    markdown.ts
```

No feature may reach into another feature’s internal implementation.

---

# 5. Layout Model

Mobile-first.

Single vertical stack layout:

```
TopBar
MainContent
BottomBar
```

MainContent swaps between:

* Document view
* Editor view
* Tree view
* Utility panels

On wider screens, a simple two-pane layout may be used:

```
Document | SidePanel
```

No complex grid systems.
No nested layout logic.

Layout structure must be defined in `MainLayout.svelte` and not redefined elsewhere.

---

# 6. State Model

Minimal reactive stores:


### document.ts

* current node address (e.g. /chapter-1)
* raw markdown content
* rendered HTML
* transaction state
* cursor position
* unstaged range markers

### ui.ts

* active panel
* editor mode vs read mode
* modal visibility

Stores must remain flat and simple.

No nested complex reactive trees.

---

# 7. Markdown Rendering

Use `markdown-it` for rendering.

Rules:

* Rendering happens only in `MarkdownView.svelte`.
* No direct DOM injection elsewhere.

Rendering flow:

Raw markdown (store)
→ markdown-it render
→ sanitized HTML
→ injected into container

Rendering must not mutate state.

---

# 8. Editor

CodeMirror 6 configured minimally.

Features enabled:

* Line numbers
* Markdown syntax highlighting
* Selection tracking
* Programmatic range replacement

Features explicitly disabled:

* Auto formatting
* Code folding
* Autocomplete
* Linting
* Plugins beyond core markdown

The editor component:

* Accepts `value`
* Emits `onChange`
* Exposes `replaceRange(startLine, endLine, text)`
* Emits `selectionChanged`

The rest of the app does not manipulate editor internals.

---

# 9. SSE Model

SSE logic lives only in `services/sse.ts`.

Responsibilities:

* Open EventSource
* Handle reconnects
* Dispatch events to subscribers
* Close cleanly

No component may directly instantiate EventSource.

Streaming flow:

Operator invoked
→ backend returns SSE stream
→ sse service emits tokens
→ StreamPanel appends tokens
→ On complete, result committed to store

Streaming must not directly mutate DOM outside reactive store updates.

---

# 10. API Interaction Model

All HTTP calls live in `services/api.ts`.

* fetch wrappers
* auth header injection
* error normalization
* response parsing

No component performs raw fetch calls.

---

# 11. Authentication

Authentication is handled entirely at the reverse proxy layer (Caddy).

The frontend does **not** implement:

* Login screens
* Bearer headers
* Refresh tokens
* Session management
* WebAuthn flows

Instead:

* Caddy enforces HTTPS.
* Caddy enforces HTTP Basic Authentication.
* Only authenticated requests reach the FastAPI application.
* The browser automatically includes credentials for all requests once authenticated.

The frontend assumes:

> If the page loaded, the user is authenticated.

---

## Frontend Responsibilities

The frontend:

* Does not store authentication state.
* Does not attach Authorization headers.
* Does not handle 401 responses (except as fatal).
* Does not implement login UI.

If a 401 is received:

* The browser will trigger re-authentication via the HTTP Basic challenge.
* The frontend does not intervene.

---

## SSE Considerations

SSE works transparently behind Caddy Basic Auth.

The browser:

* Automatically includes Basic Auth credentials with EventSource requests.
* No token injection is required.

No special handling is needed in the frontend SSE implementation.

---

## Security Assumptions

* All traffic is HTTPS.
* Caddy handles TLS certificates automatically.
* The server is not exposed directly.
* FastAPI listens on localhost or private interface only.

The frontend must never assume public access is possible without passing Caddy.

---

# 12. Transaction Visibility & Control

Unstaged changes must be visually distinct.

Approach:

* Subtle border or background indicator
* TopBar badge showing transaction state
* Highlighting of affected line ranges in editor

The UI must provide explicit controls for:

*   **Rollback**: Discard unstaged changes.
*   **Commit**: Stage the current transaction.
*   **Checkpoint**: Push all staged changes to the remote repository (git push).

No git terminology should be exposed to the user (e.g. use "Save to Cloud" or "Checkpoint" instead of "Push").

---

# 13. Tree Navigation

TreeBrowser displays:

* Current node
* Parent link
* Children list
* Indicators if sub-node exists

Click navigates by updating current node in document store and fetching content.

Tree structure is provided by backend.
Frontend does not derive hierarchy logic.

---

# 14. Testing Strategy

Use Playwright for:

* Login flow
* Load document
* Enter edit mode
* Select lines
* Trigger operator
* Validate streaming response
* Validate commit state

No unit tests for trivial components.
Focus on integration behavior.

Playwright ensures UI stability against LLM-generated modifications.

---

# 15. Deployment Model

Production:

* `vite build`
* Static assets served by FastAPI
* Same origin for API and frontend
* SSE served from same domain
* No CORS needed

Instance model:

* Each instance has:

  * Backend container
  * Cloned Lens repo
  * Cloned content repo
  * Secrets injected at runtime

Frontend is static bundle inside backend container.

No CDN required.

---

# 16. Guardrails for LLM-Generated Changes

These constraints must be documented in the repository:

1. Do not introduce additional frameworks.
2. Do not move network logic into components.
3. Do not modify layout hierarchy without explicit request.
4. Do not configure CodeMirror outside editor component.
5. Do not introduce global CSS.
6. Do not manipulate DOM manually outside Svelte bindings.
7. Always use narrative ADDRESS paths (e.g. /chapter-1) for node identification, never internal IDs.

Architecture violations must be rejected in review.

---

# 17. Non-Goals

* Multi-user collaboration
* Theming systems
* Plugin ecosystems
* IDE-level editing
* Realtime collaborative editing
* SSR rendering
* SEO optimization

This is a private tool.

---

# 18. Philosophy

The frontend is:

* A controlled surface
* A deterministic shell
* A minimal reactive layer

Its job is to:

* Display state
* Send intent
* Stream output
* Visualize transaction boundaries

On refresh, the app must fetch the current project state (including the cursor position) from the backend to restore context, rather than relying on client-side routing.

Nothing more.
