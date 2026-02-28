# Lens Backlog

## General Backlog  
- **Operator tools**: let the LLM switch operators  
  - Define function tools to apply operators. Each tool includes:  
    - operator slug, unique id (may be optional), and operator parameters schema  
    - whether the LLM response text is part of the narrative (i.e. "hand off to this operator after what I wrote") or is to be dropped and not stored in narrative node (i.e. "I was just thinking out loud, ignore my response and just call the operator")
    - whether the current operator should be closed before handing off (e.g. a `section` may remain open, but a `write` would close since it doesn't nest other nodes). If the operator wants to close AND ignore its response, it would generate a self-closing tag (i.e. it was just called for its side-effects)
  - These are extensible: operators define their own tool definition and (if the current dataset supports the operator) they are added to the request metadata.
  - The operator also defines a prompt snippet with instructions on what the operator is, so the LLM has context of when to call; these snippet are appended to the system prompt
  - When a response return, a pre-processor looks for tool calls in the response and  
    1. Appends or discards the response text based on the related parameter
    2. Calls the operator, which will add its annotation to the cursor and perform its logic as usual. This system can chain multiple tool and LLM calls, so it's effectively an agentic loop and may need safeguards; for now allow the manually-invoked operator to call another, but further calls require user confirmation with a preview of output so far and what's being called.
  - Note that there is no "callback" of the original operator, it's always a hand off (not a stack). The original operator cedes control and is done; the child may call a _new_ instance of that operator to wrap things up (it could be part of the request even), but that's it.

## Operator Backlog  
  - `remember` could integrate some aspects of a given text into a new or existing knowledge object.
    - For example, one could be talking with an NPC and then ask the operator to update `person.name`: the operator looks at the person template to see what kind of facts this knowledge item tracks, and then gathers what we learned into that object, either by creating it or integrating new knowledge. 
    - The user could apply the operator to the same text towards multiple objects, and only the details relevant to that object would be captured. For example, a scene can be remembered for the city location, market location, and a specific merchant encountered, but not for other merchants or other details.
    - _Why?_ I need targeted changes that are mo sticky than summaries, which are more the narrative than the current state
  - `play` could be like write, but has knowledge of who the player and non-player characters in the story are (like, use kb tags). It generates text in a way that delegates agency to the player characters (does not write what they think, feel, decide, or do), giving the user the space to make those decisions.
    - The opposite could also be true, where the user asks the AI to "play as" a character (autonomously or with direction). This allows the user to be the DM and/or players, maintaining that role isolation in the narrative beats. 
    - _Why?_ This is the baseline "writing style" I need to always occur when I'm not writing open-ended narrative
  - `dnd` could be even more specialized than `play`, and even be a family of D&D operators: having the user have player characters merely attempt difficult actions using the D&D ruleset, and having a conversation with the AI on what checks could be used (e.g. "Roll a stealth check to try to sneak by the guards"); the human could then roll dice and use RPG character sheets of their player characters; the AI then makes a determination of level of success and moves the narrative forward accordingly. 
    - The raw exchange (all the checks and rolls) would be in a sub-node, but only the result would be part of the parent narrative (specialized summary)
    - _Why?_ I believe I have some key insights on this in my old AI DM Manual, but it lacked disciplined context management (I had to hack it with scripts): now I have everything I need to keep the AI focused on what matters: it should work!
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
