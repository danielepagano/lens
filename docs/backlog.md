# Lens Backlog

## General Backlog
- **Background KB extraction** *(infrastructure, not a player operator)*  
  Faceted context compression: the write-side complement to RAG. A cheap/fast model (8B or equivalent) runs over recently committed narrative and updates opted-in KB objects using per-type extraction instructions. This also replaces any need for a dedicated `lore` operator: mid-campaign world amendments are just free `agent` chat, and extraction at checkpoint makes them stick into the right KB objects. Key design decisions:
    - **Trigger**: checkpoint. Runs when the user commits a checkpoint, which already has the right semantics (deliberate, meaningful boundary). Produces a single transaction with all proposed KB changes for user review — same audit pattern as the `edit` operator.
    - **Opt-in via dot-tag**: an object is eligible for extraction only if it carries a `remember.*` dot-tag (e.g. `remember.person` on `person.alice`). The `remember.person` KB object contains the extraction instructions and template hints for that type. One tag solves both the locking problem (only explicitly opted-in objects are touched) and the hint delivery problem (instructions live in the linked object, not in the object being updated).
    - **In-narrative signal**: the AI can emit `<!-- ai:remember:type.key -->` as a plain HTML comment in narrative output to flag that a specific object should be queued for extraction at the next checkpoint. This is a deterministic Lens trigger, not a tool call — Lens detects it on parse and queues accordingly. The AI emitting this is saying "something just happened that Alice should probably remember."
    - **Diffed, not overwritten**: the cheap model returns a full proposed object; Lens uses git transactions to effectively diff it against the current version and gives a human-reviewable audit trail.
    - This replaces the need for the expensive narrative model to call a kb tool to remember things — it just produces narrative and signals intent; extraction handles persistence as infrastructure.

## Operator Backlog
  - `design` — Campaign and world-building operator. Session Zero sub-tree: the conversation is the workspace, KB objects are the product. Produces `pc.*`, `npc.*`, `loc.*`, `faction.*`, `front.*`, `ref.rules`, and `state.adventure` objects. Output is **not narrative** — the model emits structured fenced blocks (YAML or similar) that Lens parses and extracts mechanically into KB files. Public content is plain text within the blocks; secrets and hidden agendas go in `<!-- ai:secret: -->` HTML comments inside the block content (ROT13-encoded by Lens). Driven by a pinned design dataset of KB objects rather than a large system prompt. Sections can be reopened non-linearly to iterate on any phase. See `rpg-design.md` for full spec.

  - `play` *(basic version implemented)* — GM-voice narrative that preserves player agency. Player = director, AI = author; player input is directorial intent, never prose. Two modes: flow (default, world breathes) and stakes (risk is live, check may be called). Authority model holds the director/author boundary cooperatively — same mechanism as prompt injection resistance, applied in good faith. See `rpg-design.md` for full spec.

  - `encounter` — Combat sub-node. Trigger: initiative is being tracked (player invokes explicitly). Setup phase establishes location, enemy goals, and encounter weight. Running phase: AI narrates enemy tactical intent as director ("the wounded one falls back"); player resolves all mechanics and reports outcomes. Sub-node closes with a narrative summary to the parent section. Cinematic violence that doesn't go to initiative stays in `play`.

  - `advance` — Time-passage operator. Triggered explicitly by the player passing time (rest, travel, downtime). Gives the world its turn: fronts tick (story beats advance, rough timers decrement), NPCs act on their plans, consequences of earlier choices land. Updates KB objects via the kb tool call. Creates the next section with appropriate front matter pins and an opening situation. Can interrupt the rest with world events. See `rpg-design.md` for front-as-drama design.

  - `converse` — Explicit characters chat sub-node. Gives the AI strong direction to talk more and not advance the plot — the opposite impetus from `play`. Not targeted at a single NPC; covers any conversational scene (one NPC, several, a council, an interrogation). Player directs conversational goals; AI voices all participants. Summarizes on close as what changed (relationships, information revealed, decisions made), not as a transcript.

  - `agent` just a normal agent chat about whatever with the option to remember what was said into any kb object; good for fleshing out lore outside `design`.

  - `attach` could allow you to attach media within a node: images of characters, maps, reference; you can also use model to look at images and generate text.


## Lens Web App Sequencing

*Now I can do this from my phone!*

### Milestone 0: Transaction & Persistence Layer
*   **Transaction Abstraction**: Create a Core service to report "staged" vs "committed" state without exposing Git-specific terminology.
*   **Checkpoint API**: Implement "checkpoint" functionality (commit to git and push to origin if origin is set). The idea is that API should not need to call Git.
*   **Raw Editing API**: Expose simple raw file editing API that allows modifying files without breaking transaction state (multiple changes of this type can just be one transaction). The API should not read or modify files directly, it needs to go through our storage layer.
*   *Goal: Transactional safety and Git operations abstracted into a clean Core service.*

### Milestone 1: The `lens serve` CLI & Basic API
*   **`lens serve`**: Implement the command to launch the server from inside a project repo.
*   **FastAPI Foundation**: Setup FastAPI with health checks and project loading/validation of `lens.toml`.
*   **Read-only Endpoints**:
    *   `GET /status`: Project config, current address (cursor), and transaction state.
    *   `GET /tree`: Narrative hierarchy for the TreeBrowser.
    *   `GET /node/{address}`: Raw content and metadata for a specific node.
*   *Goal: A functional REST server capable of reporting project and node state.*

### Milestone 2: Web Shell & Read-Only Viewer
*   **Frontend Setup**: Svelte + Vite + Pico.css project structure with mobile-first vertical stack.
*   **TreeBrowser**: Sidebar/panel for navigating narrative nodes.
*   **MarkdownView**: Render node content using `markdown-it`.
*   **Session Persistence**: On app load, fetch `/status` to restore user's current node and scroll position.
*   *Goal: A mobile-friendly web explorer for Lens narratives.*

### Milestone 3: Deployment, Serving & Security
*   **`lens serve prod`**: Serving built assets directly from the FastAPI server.
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
