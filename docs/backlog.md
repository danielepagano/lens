# Lens Backlog

## RPG Play Sequencing

### Phase 1: Single Scene Play
- Iterate on `play` system prompt until the authority model holds — the AI authors the world without narrating PC choices or pre-declaring roll outcomes
- Test flow mode: does the world breathe? Can a scene develop without manufactured pressure every beat?
- Test stakes mode: does the AI establish risk, call the right check type and DC, and wait for roll results before narrating?
- *Goal: a single scene that feels like playing an RPG — responsive, surprising, cooperative*

### Phase 2: Weave Skills, Dialogue, and Combat
- Implement `encounter` and play through a combat in the test scene
- Implement `converse` and play through a dialogue with an NPC
- Test that transitions between `play`, `converse`, and `encounter` feel natural — mode switches should be invisible to the fiction
- *Goal: a scene that can explore, talk, and fight in the same session*

### Phase 3: Connect Two Scenes
- Implement `advance` — player passes time, world takes its turn, next scene opens
- Test that active fronts feel alive: something changed while the party wasn't watching
- *Goal: a two-scene "session" with a world that moves*

### Phase 4: Formalize Setup
- Build the design dataset KB objects: session zero phase sequence, KB object templates, example adventure questions
- Implement `design` — now there is a working game to design for; the operator formalizes what play has already revealed about what data matters
- Run a session zero for a short one-shot and play it through Phases 1–3
- *Goal: a complete session zero → play pipeline for a small adventure*

### Phase 5: Scale
- Background KB extraction (see General Backlog)
- Longer adventures, multi-session fronts, richer faction and NPC networks
- Let scope grow with demonstrated need

## General Backlog

- **`attach` Operator** — Attach media (images, maps, references) within a node; optionally generate descriptive text from images.
- **Background KB extraction** *(infrastructure, not a player operator)*
  Faceted context compression: the write-side complement to RAG. A cheap/fast model (8B or equivalent) runs over recently committed narrative and updates opted-in KB objects using per-type extraction instructions. This also replaces any need for a dedicated `lore` operator: mid-campaign world amendments are just free `agent` chat, and extraction at checkpoint makes them stick into the right KB objects. Key design decisions:
    - **Trigger**: checkpoint. Runs when the user commits a checkpoint, which already has the right semantics (deliberate, meaningful boundary). Produces a single transaction with all proposed KB changes for user review — same audit pattern as the `edit` operator.
    - **Opt-in via dot-tag**: an object is eligible for extraction only if it carries a `remember.*` dot-tag (e.g. `remember.person` on `person.alice`). The `remember.person` KB object contains the extraction instructions and template hints for that type. One tag solves both the locking problem (only explicitly opted-in objects are touched) and the hint delivery problem (instructions live in the linked object, not in the object being updated).
    - **In-narrative signal**: the AI can emit `<!-- ai:remember:type.key -->` as a plain HTML comment in narrative output to flag that a specific object should be queued for extraction at the next checkpoint. This is a deterministic Lens trigger, not a tool call — Lens detects it on parse and queues accordingly.
    - **Diffed, not overwritten**: the cheap model returns a full proposed object; Lens uses git transactions to effectively diff it against the current version and gives a human-reviewable audit trail.

---

## Lens Web App Sequencing

*Now I can do this from my phone!*

See [API Design](./api-design.md) and [App Design](./app-design.md) for key guidelines.

### [DONE] Milestone 1: The `lens serve` CLI & Basic API. See [here](../lens/server/README.md).

### Milestone 2: Web Shell & Read-Only Viewer
*   **Frontend Setup**: Svelte + Vite + Pico.css project structure with mobile-first vertical stack.
*   **TreeBrowser**: Sidebar/panel for navigating narrative nodes.
*   **MarkdownView**: Render node content using `markdown-it`.
*   **Session Persistence**: On app load, fetch `/stats` to restore user's current node and scroll position.
*   **Tested**: Wired into e2e test framework.
*   *Goal: A mobile-friendly web explorer for Lens narratives.*

### Milestone 3: Deployment, Serving & Security
*   **`lens serve`**: Serving built assets directly from the FastAPI server.
*   **Security Layer**: Caddy configuration for HTTPS and Basic Auth as the primary security boundary.
*   **Deployment Docs**: Documentation for deploying to fly.io or similar.
*   *Goal: A secure, deployable, read-only view of the narrative.*

### Milestone 4: Transactional Mutation & Node CRUD
*   **Transaction Control**: Endpoints and UI for `POST /rollback` and `POST /commit`.
*   **Visual Indicators**: Highlight unstaged changes and transaction boundaries in the UI.
*   **Node CRUD**: APIs and UI for creating nodes and swapping between leaf/branch nodes.
*   *Goal: Ability to modify narrative structure and manage transactions via the web UI.*

### Milestone 5: The Editor & Knowledge Store
*   **CodeMirror Integration**: Integrate CodeMirror 6 for manual markdown editing.
*   **KB Browsing & Editing**: UI for browsing, editing, and deleting knowledge objects.
*   **KB Pinning**: UI for pinning/unpinning KB objects to nodes.
*   *Goal: A full manual web editor and knowledge manager for Lens projects.*

### Milestone 6: AI Streaming & Operators
*   **Streaming Endpoints**: Implement `write` and `edit` operators using Server-Sent Events (SSE).
*   **Stream Management**:
    *   `POST /cancel` to interrupt an active LLM stream.
    *   Frontend **StreamPanel** to display real-time tokens before commitment.
*   **Line-Aware Controls**: Implement the "After-the-fact sectioning" and "Edit range" UI in CodeMirror.
*   *Goal: Full AI-assisted narrative creation in the web app.*
