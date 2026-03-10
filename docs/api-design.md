# Lens Backend: Adding FastAPI to an Existing CLI Codebase

## 1. Goal

Introduce a FastAPI REST + SSE server as an alternative entry point to the existing CLI, without:

* Duplicating domain logic
* Forking behavior between CLI and server
* Refactoring the core into a framework-dependent mess
* Introducing unnecessary async complexity

The CLI remains first-class.
The server is an adapter layer.

---

# 2. Architectural Principle

**CLI and API are both interfaces to the same application core.**

Never:

* Put business logic in FastAPI routes.
* Put HTTP concepts inside core modules.
* Put CLI parsing logic inside domain code.

You want this layering:

```text
                  Web UI
                   |
            CLI  FastAPI
             |     | 
            Lens Core (Domain)
                |
         Filesystem / Repo
```

FastAPI and CLI are siblings.

---

# 3. Refactoring for Dual Entry Points

For the most part, we already split some commands from the rest, but we need to also split operators CLI and remove any logic from commands that should be in core modules (they should be thin wrappers).

## 3.1 Core Domain Layer (Pure Python)

Contains:

* Storage and projects
* Narrative, knowledge, and structure
* LLM integration
* Operators (split the current operator typer code to matching commands)

No:

* print() except diagnostically
* argparse/typer
* HTTP server
* JSON serialization

---

## 3.2 Application Layer

This layer:

* Accepts structured input
* Calls domain logic
* Returns structured output
* Handles security
* Wraps streaming responses (generators)

CLI is one, and FastAPI is being added.

---

# 4. FastAPI Integration Strategy

## 4.1 Directory Structure

```text
lens/
  cli/
  core/
  server/
    main.py
    routes/
    sse.py
    dependencies.py
```

Keep server code isolated. It imports from `core/`, never from `cli/`.

---

# 5. REST Layer Design Principles

FastAPI routes must:

* Validate input (Pydantic)
* Call core layer
* Return structured JSON
* Translate domain errors to HTTP errors
* Abstract transaction status (expose "staged" vs "committed" state without exposing Git internals)

Routes do not:

* Modify filesystem directly
* Parse markdown
* Implement transaction logic
* Contain streaming logic beyond adapter

They are thin adapters (like CLI commands).

---

# 6. SSE Integration

LLM generate already supports streaming output. 
The SSE adapter wraps the generator. FastAPI handles:

* Converting generator to EventSource response
* Content type
* Connection lifetime

Keep streaming logic outside the core.

---

# 7. Async Strategy

Do NOT rewrite everything async. Instead:

* Keep domain sync.
* Use FastAPI normally.
* Wrap blocking calls in threadpool if needed.

Example:

```python
from fastapi.concurrency import run_in_threadpool
```

Only use async if:

* You are awaiting non-streaming network calls
* You truly benefit from it.

Do not infect the core with async unless required. Async is contagious. Contain it at the edges.

---

# 8. Configuration & Secrets

In a way, it's the content repo that's running the server to edit itself; all the config and secrets continue to be in lens.toml.

The server is launched via the CLI:

```bash
lens serve         # Build frontend and serve from FastAPI
lens dev           # Vite dev server + FastAPI (HMR)
```

The command must be run from inside a project repo. It validates and uses that repo's `lens.toml` for its lifetime.

When we start the CLI, we look for a local lens.toml.
When we start the server, it uses the same configuration logic. If the repo is empty (or only contains a README), it can perform a `lens init` logic to bootstrap.

---

# 9. Application Core APIs

The Application Core must provide structured APIs for both the CLI and FastAPI:

### 9.1 Transaction & Persistence
*   **Status**: Report "staged" vs "committed" state (abstracting Git).
*   **Checkpoint**: Commit all staged changes to the local repo and push to origin.
*   **Rollback**: Discard unstaged changes or apply compensating transactions.
*   **Commit**: Stage current pending changes (moving them from "unstaged/preview" to "staged/canon-preview").

### 9.2 Raw Content Management
*   **Raw Editing**: API to modify node files directly without breaking transaction state. This allows the Web UI to perform manual edits that are then treated as a single transaction.

Note: narrative structure changes (creating nodes, moving the cursor, deleting content) are performed by invoking existing commands and operators (`section`, `rewind`, etc.) through their core APIs — not through standalone CRUD endpoints. Leaf/branch promotion is an internal implementation detail managed transparently by those operators.

---

# 10. Authentication Strategy 


FastAPI does not implement authentication logic.

Authentication is enforced at the reverse proxy (Caddy) layer.

FastAPI:

* Trusts that any incoming request has already been authenticated.
* Does not validate tokens.
* Does not parse Authorization headers.
* Does not maintain sessions.
* Does not issue JWTs.

If a request reaches FastAPI:

> It is considered authenticated.

---

## Reverse Proxy Requirements

Caddy is configured to:

* Terminate HTTPS.
* Enforce HTTP Basic Authentication.
* Reverse proxy authenticated traffic to FastAPI.
* Prevent unauthenticated traffic from reaching the backend.

Example conceptual Caddy configuration:

```
yourdomain.com {
  basicauth {
    username <hashed-password>
  }

  reverse_proxy localhost:8000
}
```

FastAPI should:

* Bind only to localhost (e.g., 127.0.0.1:8000).
* Not expose a public port directly.

---

## SSE Considerations

Caddy must:

* Allow streaming responses.
* Not buffer SSE traffic.
* Pass through `Content-Type: text/event-stream` correctly.

Caddy supports streaming by default when proxying.

FastAPI SSE implementation remains unchanged.

---

## Operational Security Model

Security responsibilities are split:

Caddy:

* TLS
* Authentication
* Internet exposure

FastAPI:

* Application logic
* Input validation
* Domain operations

The application server must never be directly accessible from the public internet.

---

## Threat Model

This design protects against:

* Opportunistic internet scans
* Automated bot traffic
* Unauthorized casual access

This is appropriate for:

* Single-user private tools
* Non-public infrastructure
* Personal narrative systems

This design does not implement:

* Multi-user support
* Role-based access control
* Fine-grained permissions


---

# 11. Static Frontend Serving

In production:

* `vite build`
* Output to `/dist`
* `lens serve` mounts the static directory.

Example structure:

```text
server/
  static/
  main.py
```

Mount at `/`.

Backend and frontend share origin.

SSE and API are same host.

No CORS needed.

---

# 12. Dev Workflow

Development:

* CLI works independently.
* `lens dev` launches the API and Vite dev server with HMR.
* Frontend runs via Vite; Vite proxies `/health`, `/stats`, `/tree`, `/node/` to FastAPI.

Production:

* Single container or process.
* `lens serve` builds and serves the frontend bundle from FastAPI.
* FastAPI serves both API and static UI.

Keep environments symmetrical.

---

# 13. Process Model

Single process is fine. We need to support only one max LLM stream at a time.

Guidelines for stream management:

* The API must provide an endpoint to **cancel/stop** an active stream.
* The backend should ensure that only one "write" or "edit" operation is active per instance.
* Cancellation should cleanly close the LLM connection and rollback any partial filesystem changes if applicable.

---

# 14. Deployment Model

Each instance:

* Pulls Lens code
* Pulls content repo
* Has injected secrets (git key, LLM API key)
* Runs `lens serve`
* Serves static UI
* No external dependencies

Ephemeral instances are fine if:

* Content repo is persistent, or we commit+push regularly via the **Checkpoint API**.
* Secrets are injected per instance.

Stateless server + persistent repo = clean separation.

---

# 15. Testing

Add integration tests that:

* Spin up FastAPI app (via `lens serve` or `lens dev`)
* Call representative endpoints
* Validate JSON structure
* Validate SSE stream sequence

CLI tests remain unchanged.

---

# 16. Failure Boundaries

Server must:

* Catch domain exceptions
* Map to HTTP 400/500
* Close SSE cleanly on failure
* Not leak stack traces

Core must:

* Raise explicit exceptions
* Not call sys.exit()
* Not print()

---

# 17. Anti-Goals

Do NOT:

* Refactor CLI into FastAPI.
* Share route logic with CLI parsing.
* Build generic middleware layers.
* Introduce dependency injection frameworks.
* Introduce ORM.
* Introduce background task queues.
* Split into microservices.
* If Caddy is removed, the server becomes unauthenticated and must not be exposed publicly. Authentication is infrastructure-level, not application-level.
