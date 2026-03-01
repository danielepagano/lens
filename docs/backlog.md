# Lens Backlog

## General Backlog

- **Improved Section operator: chain and front matter pin support**: `section` should accept pin/un-pin parameters in its annotation and apply those to the newly created child node's front matter. It should also accept a `chain` parameter, which automatically uses the the given operator and parameters (for example to start writing in the new section). chained operators are in the same transaction and can be invoked by a single tool call. Make `chain` re-usable parameter like pin/un-pin so we can add it to other operators later.
  
  ```markdown
  [section:castle-dorn
    chain:
      play:
        prompt: party arrives at Castle Dorn; the guards are suspicious
    kb_pin: location.castle-dorn, npc.king-aldric, faction.court!
    kb_unpin: location.capital-city
  ]: #

  ```
  As shown above, the operator itself in the parent will have these parameter captured (as usual), but additionally Lens also adds the pins/unpins to the front matter section of the new node, causing subsequent context assembly for that section to automatically loads appropriate context, lore, secrets, and rules. 
  After the front matter, Lens will also output the annotation for the given chained operator and run it (this may have its own pins separately from the front matter, as usual. If that operator also has a chain, this will repeat. This allows concatenation of actions without infinite looping.

## Operator Backlog
  - `design` — Campaign and world-building operator. A structured conversation for building KB objects before or between sessions. Produces `npc.*`, `location.*`, `faction.*`, and `front.*` objects with both public lore and hidden `dm:` sections (true motivations, secrets, escalation plans). System prompt focuses on building a living world whose elements have their own goals and plans.

  - `play` *(basic version implemented)* — GM-voice narrative that preserves player agency. Implemented; the RPG-focused system prompt refinement (immersive narrator, skill check negotiation, NPC voicing, stop-for-player-input discipline) is part of the RPG operator work.

  - `encounter` — Combat narrator, replaces the earlier `dnd` operator family concept. A sub-node operator covering a full combat encounter in two phases: (1) setup — describe the encounter location, enemies with their goals, and tactically relevant terrain; (2) running — per-request enemy direction ("the wounded one falls back while the other two flank left"), respond to player-reported outcomes, close with a narrative summary that surfaces to the parent section. The player handles all mechanics; the AI narrates enemy intent only.

  - `advance` — Between-scene accounting, replaces the earlier `remember` concept. Triggered explicitly by the player (long rest, "we make camp", scene transition). Reviews what just happened, assesses active fronts (advanced / disrupted / resolved), updates relevant KB objects including their hidden `dm:` sections (NPC suspicions, front state, world changes), then creates the next section node with appropriate front matter pins and an opening situation. Gives adversaries their moves while the player rests.

  - `chat` could spin up an agentic chat in a sub-node to talk about the current goings-on. This can be used for fun ("that was crazy!"), to explore the feeling of characters off the page (maybe then by remembering the results), to plan what happens next, etc. This would be all non-canon narrative, but still contextually kept in the simulation tree; in other words, it would have a self-closing tag with an id and no content bubbled up, e.g. `[chat:reflections/]: #`.
    - _Why?_ Maybe adding it as a sub-node won't work because I need to continue it in parallel with content... but that's also not that hard. Not hard to add if needed.

  - `attach` could allow you to attach media within a node: images of characters, maps, reference; you can also use model to look at images and generate text.
    - _Why?_ Mostly useful after web app, just because seems well-rounded, I like making art, and for Nook parity... if I feel like it.


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
