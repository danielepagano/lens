# Lens - The Design

> What is it: filesystem-native, forward-only narrative trees and a knowledge store that enable modular AI-assisted creation with fractal summarization.

## Narrative Simulations

Lens is a system that allows users and AIs to collaboratively create "narrative simulations". A Narrative Simulation is essentially prose text, but generated using improvisational elements. They have the following properties:  
  1. Narrative is created in a forward-only fashion: once committed, it's canon. It's always technically possible to change the past (it's your story, your data), but the system supports this in very limited ways.
  2. Narrative is grounded by a knowledge store with arbitrary facts. Facts CAN change over time, and are used to both ground the narrative to get things started (lore, rules, etc.) and to track what has transpired
  3. Human user and AI collaborate on writing using an extensible set of operators that allow various simulations and behaviors. An operator is a function that generates or manipulates text or structure.
  4. The story is hierarchical and fractal. The top level reads like a very high-level overview of what happened so far, but each item within may just be a summary: you can zoom in on these summaries to see the more detailed story of how that text came to be, which in turn may be a series of summaries, and so on to whatever level of detail you want. This has two goals:  
     1. AI prompts use ancestor summaries at increasingly high level, maintaining high-level continuity with lower resolution for farther away facts; this is like rendering fewer triangles for geometry far away.
     2. You can use the finer details to simulate systems that generate these outcomes, which can be any operator you design, from randomness to an RPG (played within Lens, or outside of it). In other words, this can help Lens be a workspace or even a virtual GM of sorts.

## Storage Model

Each Lens project is a git repo (not the app's repo, but a content repo we point the app to). The repo acts as a database and also lets users just read Markdown files for the story they wrote, while tracking progress over time and even allowing them to  create "alternate universes" or explore "what-if scenarios" using git branches.

A Lens project has two main areas: **knowledge** and **narrative**.

### Knowledge Store

Knowledge represents the grounding facts that can both inform the narrative (rules, lore, anything established outside the narrative) or be derived by it (who we meet, world state, accumulated history, etc.)

Knowledge is simply a key-value store of objects, each with a unique id, and provides the following abstractions:  
  - Each knowledge object has a `type`, which is an arbitrary classification identifier string created by the user, like `place` or `person`.
  - Each knowledge object has a `key`, which is an identifier unique within that type. The object's globally unique ID is `type.key`
  - An object's content is simply a markdown string
  - Each `type` has a `_template`, which is a special object (usually the first one created for that type) that describes what the purpose of this object type is, and what kind of details go in it.
  - Tags can be created and assigned to objects; they facilitate retrieval and can also create a knowledge graph. Tags can be:  
    - Simple strings: `featured`, `active` (for simple search/classification)
    - Key-value pairs: `kind:region`, `act:1` (colon separator; can be used by tools to store simple structure data)
    - Object references: `place.nyc`, `person.amy` (dot separator; creates a directed relationship from one object to another)
      - We can include an object's direct references when referring to it by adding a `+` after it; so if `person.amy` has a `place.nyc` tag, we can pull nyc's content by saying `person.amy!`.
      - Dot-tags may reference objects that do not exist yet (e.g. you add `place.nyc` before creating the place); the CLI warns when displaying such invalid dot-tags.
    - Tags cannot contain both colons and dots
    - Tags are stored in `knowledge/tags.toml`, which contains Python dictionaries that map tags to the set of object IDs that have that tag, and object id's to their own tags (forward and back links).

#### Storage model

```
/<project-root>/
  knowledge/
    tags.toml          <-- tag index 
    npc/               <-- the object type
      _template.md     <-- optional template for that object type
      forgery_guy.md   <-- filename is object key, file content is object content
    place/
      needle_street.md
```

### Narrative Nodes

Narrative simulations are stories or adventures in the world defined in the knowledge. Technically no knowledge is required to use narrative (just read what happened before!) but this limits the ability for an AI to be consistent and accurate about various topics as the narrative evolves.

A unit of narrative is a **node**, which is simply a markdown file with a key unique among its siblings (exactly like a knowledge object's `key`). The node can be a standalone `key.md` which makes it a **leaf node**, or a folder with that key, using a `key/_node.md` file, which allows child nodes. Either way, the node's full ID is its full path of node keys. Child nodes are linked to the parent by using operators, which create comments in the node (hidden when Markdown is rendered).

Semantically, a node represents narrative at a certain level of detail, and at that level of detail it should be readable, cogent, and complete. The levels of detail are arbitrary and need to make sense for the situation: they could be chapters, dates, sessions, encounters, combat rounds, etc. **The key idea is that sections of a node may be results or summaries of child nodes.**

Internally, nodes are annotated using invisible [comments](https://www.markdownguide.org/hacks/#comments) in the form of `[text]: #`. In order to be properly parsed and hidden, they have to appear on their own line and have an empty line before them. While users can leave any comment they want, Lens annotations work as follows:  
  - Each annotation has to start with a known `operator` after the opening bracket, e.g. `[write`. If that is pattern-matched, the annotation is processed by Lens
  - Each operator annotation can have an ID after the operator, separated by colon, e.g. `[write:rest_1`; this ID has to be a valid filename (not an existing file, it has to follow filename patterns, like knowledge types and keys) and be unique within this node (across any operator types). If the operator uses a sub-node for storage, the node will have this name.
  - If an operator annotation has no content in the node, it should end with `/`, e.g. `[chat:reflect_about_feelings/]: #`
  - If an operator does have content in the node (its output), it should have a matching close tag later, e.g. `[write:rest_1]: #` then some lines of text, and empty line, then `[/write:rest_1]: #` (remember, ID is optional if there is no sub-node, in which case it does not have to be included)
  - Annotations can span multiple lines, but the lines after the first need to be indented by at least four spaces so they are not parsed as Markdown elements (which would break the invisible-comment rendering).
  - A special annotation called a "front matter" can be included at the beginning of a module without an operator or id, and contain YAML that is available to all operators in the node, and even its sub-nodes (if they query for it)

Examples:

```markdown
[ <-- "front matter" section for node-wide settings, used by operators
    kb_pin: <-- knowledge-aware operators always add this content, even in child nodes!
    - place.needle_street
    - place.capital_city
    kb_unpin:  <-- you can un-pin irrelevant parent pins from this sub-tree
    - front.the_demon_rises
]: #

[write
    prompt: hey you! how about a \
multiline prompt here?
    kb_pin:
    - first.key
    - second.key
]: #

This was written by the write operator above, which you can't see, but it's good to know!

[/write]: #
This text added by hand! It's good to know when the AI was done.

[section:my_elaborate_aside]: #
This looks like it goes right after the above when rendering, but it's a summary of an elaborate aside in a child node called `my_elaborate_aside`!

[/section:my_elaborate_aside]: #

Now we're just adding content to the original node!
```

The above would just render as

```markdown
This was written by the write operator above, which you can't see, but it's good to know!

This text added by hand! It's good to know when the AI was done.

This looks like it goes right after the above when rendering, but it's a summary of an elaborate aside in a child node called `my_elaborate_aside`!

Now we're just adding content to the original node!
```

Comments can also be added to knowledge MD files, and they will be skipped when sending details to any AI model; knowledge-centric operators could also be built using this mechanism.

#### The Cursor

The narrative system assumes we are forward-appending a narrative tree: that is, there is a single node in the narrative tree that is the current insertion point for new text. When starting the root node, the cursor is at the end of that document, but if we start a sub-node there, the cursor is now at the end of _that_ sub-node (the parent would have an un-closed operator annotation). Once that sub-node is completed, and its result reflected in the parent, then the cursor is again at the end of the parent document. Editing can happen anywhere, but many features are designed to operate specifically at the cursor.

As a side effect of this, to actually change what happened in a significant way, the user needs to "rewind" the narrative by deleting everything after a previous cursor. This can certainly be done for narrative, but a git checkout of that version and a branch or force-push would be better, as it will also restore the knowledge as of that point in time!

#### Storage model

```
/<project-root>/
  narrative/
    <root-key>/     <-- you can have multiple root keys for multiple narratives
      _node.md      <-- node content for root-key
      event_1/      <-- container for event_1 node
        _node.md    <-- event_1 node content
      event_2.md    <-- leaf node event_2; same as event_2/_node.md
```

## Operators

Operators manipulate text and structure, and can be controlled by parameters.

All operators leverage the system's ability to produce a working unstaged preview draft before a change is committed, which is represented by git unstaged changes. Once the draft is accepted, the change is staged. Lens uses this as a transaction system with full file-system state.

Operators may not be one-shot, instead assembling their output in multiple stages by compositing further instructions and nesting other operator calls; we call these multi-transaction operators. An uncommitted transaction is just unstaged changes, and committing the transaction stages them, completing a logical step in the operator. Because even structure is an operator, we'll have a call-chain of multi-step operators essentially the whole we use Lens, so transactions are more fine-grained than operators. Git commits can happen at any time to finalize any  completed transaction to the repo and/or origin.

Operators can act at the Cursor (like for writing new content) or in any other location (to edit, remember, manipulate structure, etc.). Either way, only one transaction at a time from any operator can be in-progress in Lens.

By design, operators can make changes in one or more of the following ways:  
  1. In the same node (or knowledge object) they are defined, before their close tag. This has two flavors:
    1. Single-step: the uncommitted changes contain both opening tag, content, and close tag
    2. Multi-step: the first step contains the opening tag, but leaves an open tag (this can happen at the cursor only); additional steps need to modify the original tag as well as add content, usually by incrementing a `steps:` counter; this way we know which operator has pending changes without having to search.
  2. At the cursor, in a narrative sub-node matching their id (if they have an id), while their tag is not closed. Creating the node itself from a parent is an obvious transaction; after that, while the operator continues it will just be appending the node, and we can easily see the unclosed tag at the end of the previous node (no need to modify it).  
    - Note that once inside a node additional operators will add more transactions; they are the owners of those changes in that case, and the original operator just created the node
    - As a special case, when a sub-node owned by an operator is closed, that operator may have a closing action (like a summary of the child node), which is itself a transaction, and closes the tag (so owner is clear as well).
  3. Mutate existing content; to do this, the operator has to proceed as follows:  
    1. Stage and auto-commit a transaction to "claim" the text to mutate by wrapping it in its tags, then  
    2. Immediately open a new transaction that includes both the proposed changes and the removal of the tags in the previous step.  
    3. If the change is no longer wanted, we need to commit a compensating transaction to reverse 1 by removing the claim tags.   
    - This design allows us to have a deterministic way to see which text has pending changes, and why, and because the pending change removes the tags, we can both leave no trace and know what was being attempted. This also allows a single mutation transaction to could cover multiple tree nodes and knowledge objects at once.  
    - In some cases we could leave dangling claim tags, but these operators should never leave tags behind, so we can easily grep the entire repo for the tags and remove them later.

With the above design, at any time Lens can look at a repo and immediately know whether any operator transaction is pending, and the change itself gives enough context to know which operator it is. 

Critically, only **one pending transaction can exist per repo**. The purpose of transactions is to allow the user to review, retry and even edit the unstaged changes directly, but also we want to keep moving, so if a user asks for a new transaction while one is pending, we auto-commit the existing transaction by staging all pending changes, and only then we begin a new one.

This means that **all** code that changes any tracked git file in a content repo **must** go through our transactional storage layer, including our knowledge system.

These are the core built-in core operators:

 - `write` generates new text to put in a new place. It can use context text or instructions on which directions to take. This can be used to move narrative forward, but also to generate knowledge, maybe using a template. Of course humans can also write directly.
   - The operator can be called multiple times to try again, or to append additional content to the original response, before it is closed. It is also normal for a human to be able to manually edit the response before it is committed.
   - The usage of this operator (and many others) is tracked in the parent node using a comment block to track that it was triggered, how, and what it created
 - `edit` makes targeted changes to a contiguous text selection using AI (for example, to shorten or correct something).
    - Unlike other operators, this is a destructive operation (previous version would be in git history). Note that users can always edit any file themselves (original or summaries) since they are just markdown files; this is an AI-assisted version of that.
- `section` lets the user create a child node at the cursor (with a slug unique for this level) with its own content; when closed, the operator summarizes the entire node and sets it as its output in the parent. Start with `lens section <id>`, close with `lens section --end`.
- `collate` creates a section "after the fact" by selecting a contiguous line range at an arbitrary node. The selection is placed in a new sub-node, immediately summarized, and the summary placed where the original selection was. Because this operation can move sub-nodes in the selected range one level down, it may make large file operations, which are captured in git history. This lets users keep adding, then compress sections (e.g. a conversation or side quest) after the fact to keep the current node at the right level of detail.
- `design` and `play` are **session operators**: they create a sub-node on first call and iterate within it. Both support swappable **modules** — KB objects with a configurable prefix (e.g. `design.*` or `rules.*`) that are pinned one-at-a-time into the session's front matter. The shared session lifecycle is implemented in `SessionOperator` (`lens/core/operators/session.py`); each operator overrides generation and close behaviour.
- The front-matter (node-level YAML storage) is used to share configuration across the node, and also to child nodes. It can be used by any operator, but initially it will be used to pin/un-pin knowledge items for Context-aware operators (see more below)

## Context-aware operator prompt assembly

When you invoke a context-aware operator such as `write` that adds content, the engine uses fractal summarization and knowledge insertion to create a prompt that tries to maximize contextual knowledge.

This sub-system has the following components:  
  - A pin/un-pin system: this can attach knowledge object ID's to the front matter (just YAML lists of IDs under `kb_pin` and `kb_unpin`)  
    - A CLI to pin/unpin from a given node helps with this. Defaults to Cursor node, but any other can be targeted
  - A component that can be given a position in the narrative (default: Cursor), plus an additional set of highest-priority pins/un-pins (operators can collect these in their configuration YAML using the same schema as front matter) and it generates a "crawl" with one or both (as requested) of:  
    1. Knowledge expansions: all KB items pinned, deduped, in priority order from farthest ancestor to nearest node. It starts from the current operator and moves upwards toward the narrative root (direct ancestors) to find all pinned knowledge. An un-pin at a lower level than a pin has precedence. This un-pin includes items gathered when an expanded node (`+`). We remove any duplicates and then we emit the content of nodes from root to child (i.e. the ones pinned in a more nested node go after). Any comments in knowledge are also skipped by this inclusion: this allows those objects to have notes (for example desired character milestones) without the AI pulling them into the prompt as if they were facts. Result is a list of expanded objects in order, with comments stripped.
    2. Ancestor narrative: hierarchial parent content (always strip comment blocks). Go upwards from current position, collecting content in node, then up the parent, going up again from where that node was included, and so on until the root. Return in root -> child order. So if you are 3 levels in—let's say semantically you have chapter, scene, and beat—and you are in chapter 3, scene 4, beat 3, the ancestor narrative includes the chapter 1 and 2 summaries, chapter 3 scene 1-3 summaries, and scene 4 beat 1-2 summaries. When adding at the Cursor, this is quite easy because it's equivalent to simply the full text of all parent nodes, but traversal from any position is also possible. Result is a list of segments in order, with comments stripped.

The result of the crawl is usually meant to be assembled into LLM prompts. These prompt includes, in order (the order matters for attention management):

- **System instructions**: operator-specific system prompt; usually static and in tagged as such, i.e. "You are a fancy author..."
- **Collected knowledge expansions**: all KB item expansions from crawl.
- **Ancestor narrative**: parent narrative context from crawl (ancestor and current node). 
- **Instructions based on operator and its configuration**: in natural language, things like "continue writing the story" or "summarize the following"; many operators have a `prompt` string that is included here to direct the AI to continue writing in a certain direction, summarize certain aspects, and so on. Specialized operators can have quite complex rule sets.

A module also exists to reliably assemble this prompt from crawl outputs into a string that works well.

### Narrative slices

The standard crawl collects narrative from the **full ancestor chain**—root through every intermediate node down to the cursor. This is the right default for narrative append operators like `write` need the fractal-summarization view of the whole story so far.

Some operators have a summarization intent, so they need a different narrative window. The `advance` operator, for example, must reason about **what happened since the last calendar tick**, not the entire story from the beginning. Including the full ancestor chain would waste context budget on distant material that has no bearing on front updates.

**Narrative slices** generalize crawl by introducing an **anchor**—a fixed point in the narrative tree from which text collection begins. The anchor is a `(node, line_end)` pair: text on the anchor node starts from `line_end` onward, skipping everything before it. When no anchor is supplied, crawl behaves exactly as described above (full ancestor chain). When an anchor is supplied, crawl replaces the ancestor narrative with a **spine walk**: the shortest path through the tree from anchor to cursor, via their lowest common ancestor.

The key properties:

1. **KB pin resolution is always full-chain.** Pins are structural (declared in front matter at each tree level), so the ancestor chain is always walked for pin/unpin resolution regardless of the anchor. Only the narrative text collection changes.
2. **Spine-only traversal.** The slice collects text only from nodes on the spine path—it does not descend into lateral subtrees. The contract is that operators like `section` and `play` summarize upward into parent narrative, so anything important from sibling branches should already appear as rolled-up prose on the spine.
3. **Anchor node partial read.** On the anchor node itself, only text from `line_end` onward is collected. On intermediate spine nodes, full text is collected. The cursor node becomes `current_content` as usual.
4. **Standard crawl as special case.** With no anchor, crawl reads all ancestors top-to-bottom—equivalent to a slice anchored at line 1 of the narrative root.

Operators that use slices are responsible for finding and validating their own anchors. For example, `advance` searches backward in narrative reading order for the most recent completed advance on the same timeline and validates the day-counter arithmetic before using it as an anchor.

## Architecture

Lens is purposely simple, and it's designed to be a stateless script. It just needs to have a file system mount, be pointed to a content repo, and have credentials to push to the repo's origin and configuration/credentials to connect to an OpenAI-compatible chat completion API endpoint. That's it: the server could have a lifecycle only around a single git commit. It may be a good fit for a fly.io sprite or the like.

When using Lens, at the very minimum the user can do three things:  
  1. Browse, read, and manually edit markdown files. Lens is not needed at all for this, as long as the user follows the structural rules of the storage system. Because we mostly rely on file system for uniqueness and such, this is mostly self-enforcing! The user could make these changes from anywhere, then push what they change.  
    - The knowledge system is reasonably specialized with its tags, so early on we'll want to create a CLI for manipulating these objects.
  2. Apply operators. Because most operators execute at the cursor, they are trivial to invoke, e.g. `lens write "introduce a suspicious vendor" -pin npc.forgery_guy`; the operator then changes a file on disk that the user can just look at or even modify; they can also change their mind `lens undo` or see if the AI has a better outcome a second time by saying `lens retry`, since the context is unambiguous.  
    - In order for this to work, lens has to be configured, of course, meaning a poe project needs to be activated and an LLM configured. We can do this by simply running lens from within the root of our project, which is identified as such by having a `lens.toml` file, created by `lens init`. Since each lens repo can have multiple narrative trees, one can be selected with `lens use my-slug`, which sets it as the current narrative in `lens.toml`.
    - The `lens.toml` file should not have credentials in it, of course, but it can say the env var names to look for those instead; we assume the current shell environment is authenticated in git
  3. Stage, commit, and push changes; `git` does this, but common operations can be offered by CLI.

This is good for development (or developers), but does not scale to, say, using Lens on your phone. To do that we need a more full-featured server that allows a UI to do the file browsing and editing, as well as the git operations. 

## Lens App

Ultimately, Lens should have a simple, text-centric UX that's like a "markdown editor with commands". A web UI somewhat similar to Claude Code may work well:
 - Most of the UI is about authoring or previewing markdown files.
 - At the bottom, a command strip that can navigate (replace main UI with results or a tree matching the file system), enter editing mode, or call operators.
   - For example we are running the simulation, and I can just say `/write introduce a suspicious vendor -pin npc.forgery_guy` and it will generate and run that write operator with that extra pin
   - You also need to be able to mark begin/end of text for creating sections, being able to zoom in and out of sections, etc. so something like `/collate my-aside /chapter-1 123 133` (or after `/collate my-aside` the UI lets you pick the node and mark the start and end) 
   - Lifecycle features like committing a checkpoint, like `/tx-checkpoint went shopping and found a forger`
 - Sufficiently user-friendly, with hints and auto-complete, and works well on a phone... maybe not as much typing if you can just tap on things.
