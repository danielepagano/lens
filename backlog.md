# Lens Backlog

## Lens Web App

This phase takes the existing CLI app adds a REST server and a web UI. We want to start with structure and infra to create a deployable minimal app that proves end-to-end capabilities, then layer on features.

### Milestone 1: Core Decoupling & Exception Handling
*   **Decouple CLI**: Extract domain logic from `lens/commands/` and `lens/operators/` into `lens/core/`.
*   **Exception-Driven Flow**: Replace `typer.echo` and `sys.exit` in Core with custom exceptions and structured return types.
*   **Pure Core**: Ensure Core logic is side-effect free (except for explicit FS/Git operations) and isolated from CLI/API concerns.
*   *Goal: Logic isolated from interface concerns and safe for programmatic use.*

### Milestone 2: Transaction & Persistence Layer
*   **Transaction Abstraction**: Create a Core service to report "staged" vs "committed" state without exposing Git-specific terminology.
*   **Checkpoint API**: Implement "checkpoint" functionality (commit to git and push to origin).
*   **Raw Editing API**: Expose raw file editing API that allows modifying files without breaking transaction state (multiple changes of this type can just be one transaction).
*   *Goal: Transactional safety and Git operations abstracted into a clean Core service.*

### Milestone 3: The `lens serve` CLI & Basic API
*   **`lens serve`**: Implement the command to launch the server from inside a project repo.
*   **FastAPI Foundation**: Setup FastAPI with health checks and project loading/validation of `lens.toml`.
*   **Read-only Endpoints**:
    *   `GET /status`: Project config, current address (cursor), and transaction state.
    *   `GET /tree`: Narrative hierarchy for the TreeBrowser.
    *   `GET /node/{address}`: Raw content and metadata for a specific node.
*   *Goal: A functional REST server capable of reporting project and node state.*

### Milestone 4: Web Shell & Read-Only Viewer
*   **Frontend Setup**: Svelte + Vite + Pico.css project structure with mobile-first vertical stack.
*   **TreeBrowser**: Sidebar/panel for navigating narrative nodes.
*   **MarkdownView**: Render node content using `markdown-it`.
*   **Session Persistence**: On app load, fetch `/status` to restore user's current node and scroll position.
*   *Goal: A mobile-friendly web explorer for Lens narratives.*

### Milestone 5: Deployment, Serving & Security
*   **`lens serve prod`**: Serving built assets directly from the FastAPI server.
*   **Security Layer**: Caddy configuration for HTTPS and Basic Auth as the primary security boundary.
*   **Deployment Docs**: Documentation for deploying to fly.io or similar.
*   *Goal: A secure, deployable, read-only view of the narrative.*

### Milestone 6: Transactional Mutation & Node CRUD
*   **Transaction Control**: Endpoints and UI for `POST /rollback` and `POST /commit`.
*   **Visual Indicators**: Highlight unstaged changes and transaction boundaries in the UI.
*   **Node CRUD**: APIs and UI for creating nodes and swapping between leaf/branch nodes.
*   *Goal: Ability to modify narrative structure and manage transactions via the web UI.*

### Milestone 7: The Editor & Knowledge Store
*   **CodeMirror Integration**: Integrate CodeMirror 6 for manual markdown editing.
*   **KB Browsing & Editing**: UI for browsing, editing, and deleting knowledge objects.
*   **KB Pinning**: UI for pinning/unpinning KB objects to nodes.
*   *Goal: A full manual web editor and knowledge manager for Lens projects.*

### Milestone 8: AI Streaming & Operators
*   **Streaming Endpoints**: Implement `write` and `edit` operators using Server-Sent Events (SSE).
*   **Stream Management**:
    *   `POST /cancel` to interrupt an active LLM stream.
    *   Frontend **StreamPanel** to display real-time tokens before commitment.
*   **Line-Aware Controls**: Implement the "After-the-fact sectioning" and "Edit range" UI in CodeMirror.
*   *Goal: Full AI-assisted narrative creation in the web app.*


## Future Operators

Operators are designed to be extended, and more can be created as specializations or hybridizations of the core operators; these allows more specific ways to manage content and interact with the narrative. Examples of operators that could be added:
  - `remember` could integrate some aspects of a given text into a new or existing knowledge object.
    - For example, one could be talking with an NPC and then ask the operator to update `person.name`: the operator looks at the person template to see what kind of facts this knowledge item tracks, and then gathers what we learned into that object, either by creating it or integrating new knowledge. 
    - The user could apply the operator to the same text towards multiple objects, and only the details relevant to that object would be captured. For example, a scene can be remembered for the city location, market location, and a specific merchant encountered, but not for other merchants or other details.
    - Recalling what is remembered is done by the text generation operators by providing them the IDs of the relevant objects to know about, as we'll see below. 
  - `play` could be like write, but has knowledge of who the player and non-player characters in the story are. It generates text in a way that delegates agency to the player characters (does not write what they think, feel, decide, or do), giving the user the space to make those decisions.
    - The opposite could also be true, where the user asks the AI to "play as" a character (autonomously or with direction). This allows the user to be the DM and/or players, maintaining that role isolation in the narrative beats. 
  - `dnd` could be even more specialized than `play` (or be a family of operators), having the user have player characters merely attempt difficult actions using the D&D ruleset, and having a conversation with the AI on what checks could be used (e.g. "Roll a stealth check to try to sneak by the guards"); the human could then roll dice and use RPG character sheets of their player characters; the AI then makes a determination of level of success and moves the narrative forward accordingly. The raw exchange (all the checks and rolls) would be in a sub-node, but only the result would be part of the parent narrative (specialized summary)
  - `chat` could spin up an agentic chat in a sub-node to talk about the current goings-on. This can be used for fun ("that was crazy!"), to explore the feeling of characters off the page (maybe then by remembering the results), to plan what happens next, etc. This would be all non-canon narrative, but still contextually kept in the simulation tree; in other words, it would have a self-closing tag with an id and no content bubbled up, e.g. `[chat:reflections/]: #`.
  - `attach` could allow you to attach media within a node.
