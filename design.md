# Lens - The Design

> What is it: filesystem-native, forward-only narrative trees and a knowledge store that enable modular AI-assisted creation with fractal summarization.

## Narrative Simulations

Lens is a system that allows users and AIs to collaboratively create "narrative simulations". A Narrative Simulation is essentially prose text, but generated using improvisational elements. They have following properties:  
  1. Narrative is created in a forward-only fashion: once committed, it's canon. It's always technically possible to change the past (it's your story, your data), but the system supports this in very limited ways.
  2. Narrative is grounded by a knowledge store with arbitrary facts. Facts CAN change over time, and are used to both ground the narrative to get things started (lore, rules, etc.) and to track what has transpired
  3. Human user and AI collaborate on writing using an extensible set of operators that allow various simulations and behaviors. An operator is a function that generates or manipulates text or structure.
  4. The story is hierarchical and fractal. The top level reads like a very high-level overview of what happened so far, but each item within may just be a summary: you can zoom in on these summaries to see the more story detailed story of how that text came to be, which in turn may be a series of summaries, and so on to whatever level of detail you want. This has two goals:  
     1. AI prompts use ancestor summaries at increasingly high level, maintaining high-level continuity with lower resolution for farther away facts; this is like rendering fewer triangles for geometry far away.
     2. You can use the finer details to simulate systems that generate these outcomes, which can be any operator you design, from randomness to an RPG (played within Lens, or outside of it). In other words, this can help Lens be a workspace or even a virtual DM of sorts

## Storage Model

Each Lens project is a git repo (not the app's repo, but a content repo we point the app to). The repo acts as a database and also lets users just read Markdown files for the story they wrote, while tracking progress over time and even allowing them to  create "alternate universes" or explore "what-if scenarios" using git branches.

A Lens project has two main areas: **knowledge** and **narrative**.

### Knowledge Store

Knowledge represents the grounding facts that can both inform the narrative (rules, lore, anything established outside the narrative) or be derived by it (who we meet, world state, accumulated history, etc.)

Knowledge is simply a key-value store of objects, each with an unique id, plus provides the following abstractions:  
  - Each knowledge object has a `type`, which is an arbitrary classification identifier string created by the user, like `place` or `person`.
  - Each knowledge object has a `key`, which is an identifier unique within that type. The object's globally unique ID is `type.key`
  - An object's content is simply a markdown string
  - Each `type` has a `_template`, which is a special object (usually the first one created for that type) that describe what the purpose of this object type is, and what kind of details go in it.
  - Tags can be created and assigned to objects; they facilitate retrieval and can also create a knowledge graph. Tags can be:  
    - Simple strings: `featured`, `active` (for simple search/classification)
    - Key-value pairs: `kind:region`, `act:1` (colon separator; can be used by tools to store simple structure data)
    - Object references: `place.nyc`, `person.amy` (dot separator; creates a directed relationship from one object to another)
      - We can include an object's direct references when referring to it by adding a `!` after it; so if `person.amy` has a `place.nyc` tag, we can pull nyc's content by saying `person.amy!`.
      - Dot-tags may reference objects that do not exist yet (e.g. you add `place.nyc` before creating the place); the CLI warns when displaying such invalid dot-tags.
    - Tags cannot contain both colons and dots
    - Tags are stored in `knowledge/tags.toml`, a python dictionary that goes from tag string to the set of strings, which is the set of objects that have that tag; in the case of object reference tags, that is equivalent to that object's back-links.

#### Storage model

```
/<project-root>/
  knowledge/
    tags.toml          <-- an index of all tags and the object ID's that have that tag (python dict) 
    npc/               <-- the object type
      _template.md     <-- optional template for that object type
      forgery_guy.md   <-- filename is object key, file content is object content
    place/
      needle_street.md
```

#### Project templates

It may be quite complex to define a good set of knowledge object types and templates, and sometimes operators may even require certain types. To facilitate this, we can easily define a project template as the set of object type templates, which can be pre-copied to a new project.

### Narrative Nodes

Narrative simulations are stories or adventures in the world defined in the knowledge. Technically no knowledge is required to use narrative (just read what happened before!) but this limits the ability for an AI to be consistent and accurate about various topics as the narrative evolves.

A unit of narrative is a **node**, which is simply a markdown file with a key unique among its siblings (exactly like a knowledge object's `key`). The node can be standalone `key.md` which makes it a **leaf node**, or a folder with that key, using `key/_node.md` file, which allows child nodes. Either way, the node's full ID is its full path of node keys. Child nodes are linked to the parent by using operators, which create comments in the node (hidden when Markdown is rendered).

Semantically, a node represent narrative at a certain level of detail, and at that level of detail it should be readable, cogent, and complete. The levels of details are arbitrary and need make sense to the situation: they could be chapters, dates, sessions, encounters, combat rounds, etc. **The key idea is sections of a node may be the results or summaries of child nodes.**

Internally, nodes are annotated using invisible [comments](https://www.markdownguide.org/hacks/#comments) in the form of `[comment]: #`. In order to be properly parsed and hidden, they and they have to appear on their own line and have an empty line before them; if they multi-line, they should indented to avoid problems. Examples:

```markdown
[ <-- invisible "front matter" section for global settings, used by operators
  kb_pins: <-- knowledge-aware operators always add this content, even in child nodes!
    - place.needle_street
    - place.capital_city
  kb_unpin:  <-- you can un-pin irrelevant parent pins from this sub-tree
    - front.the_demon_rises 
]: #

[ 
  op:write
  prompt: hey you! how about a \
multiline prompt here?
  kb_pins: 
    - first.key
    - second.key
]: #

This was written by the op:write above, which you can't see, but it's good to know!

[/op:write]: #
This text added by hand! It's good to know when the AI was done.

[section:my_elaborate_aside]: #

This looks like it goes right after the above when rendering, but it's a summary of an elaborate aside in a child node called `my_elaborate_aside`!

[/section:my_elaborate_aside]: #

Now we're just adding content to the original node!
```

The above would just render as

```markdown
This was written by the op:write above, which you can't see, but it's good to know!

This text added by hand! It's good to know when the AI was done.

This looks like it goes right after the above when rendering, but it's a summary of an elaborate aside in a child node called `my_elaborate_aside`!

Now we're just adding content to the original node!
```

Comments can also be added to knowledge MD files, and they will be skipped when sending details to any AI model; knowledge-centric operators could also be built using this mechanism.

### The Cursor

The narrative system assumes we are forward-appending a narrative tree: that is, there is a single node in the narrative tree that is the current insertion point for new text. When start the root node, the cursor is at the end of that document, but if we start a sub-node there, now the cursor is at the end of _that_ sub-node. Once that sub-node is completed, and its result reflected in the parent, then the cursor is again at the end of parent document. Editing can happen anywhere, but many features are designed to operate specifically at the cursor.

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
  - All operators leverage the system's ability to produce a working un-staged preview draft before the change is committed. Once the draft is accepted, the changed is staged, and the operator is "closed".
  - Operators may not be one-shot, instead assembling their output in multiple stages, by compositing further instructions and other operators; in that case, their state is committed to disk after every step, but it's reflected in a sub-node, acting as a workspace. Ony when the operator is closed is the original target of the operator updated. The intermediate node may be considered "disposable" technical output (if it just creates a result) or be a more detailed version of the canon it propagates up (if the node content is summarized).

There are several built-in core operators:

 - `write` generates new text to put in a new place. It can use context text or instructions on which directions to take. This can be used to move narrative forward, but also to generate knowledge, maybe using a template. Of course humans can also write directly.
   - The operator can be called multiple times to try again, or to append additional content to the original response, before it is closed. It is also normal for a human to be able to manually edit the response before it is committed.
   - The usage of this operator (and many others) is tracked in the parent node using a comment block to track that it was triggered, how, and what it created
 - `summarize` summarizes existing text (optionally with instructions on what to emphasize or ignore) to store it in another place (a less-detailed node, a knowledge item, etc.)
   - Summaries are critically important to maintaining the correct continuity over time, so the prompts used can be heavily curated, and the results manually tweaked.
   - Summaries are usually leveraged by other operators, notably `section`.
- `edit` makes targeted changes to a contiguous text selection using AI (for example, to shorten or correct something). It can also summarize, but the point is that it replaces text, it doesn't put its output in a new place.  
    - Unlike other operators, this is a destructive operation (previous version would be in git history). Note the that users can always edit any file themselves (original or summaries) since they are just markdown files; this is  an AI-assisted version of that.
 - `section` lets the user create a child node with its own content, which when closed is summarized in the current node; in other words, it breaks narrative into sub-sections, like chapters and scenes. It can be used in two ways:
    - A section can be explicitly started with empty content, which just creates a node, for example if we wanted to track a gaming session in its own section and summarize it in the campaign journal above.
    - Users can also create sections after the fact by selecting a contiguous section of node text that must span whole sub-nodes if any. The selection is placed in a new sub-node, summarized, and the summary placed where the original selection was.  
      - Because this operation can move sub-nodes in the selected range one level down, it may make large file operations, which are captured in git history.  
      - This feature is important because we don't know want the user to always be worried about structure: they should be able to always keep adding, then  compress sections (like a conversation or a side quest) after the fact to keep the current node at the right level of detail.
- `remember` integrates some aspects of a given text into a new or existing knowledge object.
  - For example, one could be talking with an NPC and then ask the operator to update `person.name`: the operator looks at the person template to see what kind of facts this knowledge item tracks, and then gathers what we learned into that object, either by creating it or integrating new knowledge. 
  - The user could apply the operator to the same text towards multiple objects, and only the details relevant to that object would be captured. For example a scene can be remember for the city location, market location, and a specific merchant encountered, but not for other merchants or other details.
  - Recalling what is remembered is done by the text generation operators by providing them the IDs of the relevant objects to know about, as we'll see below. 

Operators are designed to be extended, and more can be created as specializations or hybridizations of the core operators; these allows more specific ways to manage content and interact with the narrative. Examples of operators that could be added:
  - `play` could be like write, but has knowledge of who the player and non-player characters in the story are. It generates text in a way that delegates agency to the player characters (does not write what they think, feel, decide, or do), giving the user the space to make those decisions.
    - The opposite could also be true, where the user asks the AI to "play as" as character (autonomously or with direction). This allows the user to be the DM and/or players, maintaining that role isolation in the narrative beats. 
  - `dnd` could be even more specialized than `play` (or be a family of operators), having the user have player characters merely attempt difficult actions using the D&D ruleset, and having a conversation with the AI on what checks could be used (e.g. "Roll a stealth check to try to sneak by the guards"); the human could then roll dice and use RPG character sheets of their player characters; the AI then makes a determination of level of success and moves the narrative forward accordingly. The whole exchange would be in a node, the checks and rolls would be there, but only the result would be part of the narrative (specialized summary)
  - `chat` could spin up an agentic chat in a sub-node to talk about the current going on's. This can be used for fun ("that was crazy!"), to explore the feeling of characters off the page (maybe then by remembering the results), to plan what happens next, etc. This would be all non-canonic narrative, but still contextually kept in the simulation tree.
  - `attach` could allow you to attach media within a node 

There is no particular reason to keep operators in the main Lens repo: they can also be imported as external packages or even defined in the project repo next to narratives and knowledge objects.

## Context-aware operator prompt assembly

When you invoke a context-aware operator such as `write` that adds content, the engine uses fractal summarization and knowledge insertion to create a prompt that tries to maximize contextual knowledge.

This prompt includes, in order (the order matters for attention management):

- **System instructions** (operator-specific system prompt; usually static).
- **Collected knowledge expansions** (all KB items pinned or added, deduped, in priority order from farthest ancestor to nearest node).
  - Any comments in knowledge are also skipped by this inclusion: this allows those objects to have notes (for example desired character milestones) without the AI pulling them into the prompt as if they were facts.
  - Because knowledge items are meant to mutate, calling the same operator with the same knowledge over time will have different results! Using git allows us to know when this operator was called, and thus what the knowledge state was at the time.
- **Ancestor narrative** (root → parent), content of each parent node (always strip comment blocks). 
  - These are a "zoom-out" values, so usually summaries. So if you are 3 levels in, let's say semantically you have chapter, scene, and beat, and you hare in chapter 3, scene 4, beat 3, the ancestor narrative includes the chapter 1 and 2 summaries, chapter 3 scene 1-3 summaries, and scene 4 beat 1-2 summaries. 
  - When adding at the Cursor, this quite easy because it's equivalent to simply the full text of all parent nodes (minus any comments). If operating in the middle, we'd have to trim the tree more carefully with anything that would happen after this.
- **Current node narrative**. The narrative text before this operator in this node, if any. If adding to Cursor, simply the current node text. 
- **Instructions based on operator and its configuration** (in natural language, for example the `write` operator has a `prompt` string telling the AI to continue writing in a certain direction, while a `summary` operator tells the AI to summarize the "Current node narrative").

## Data Lifecycle

There are three persistence levels in Lens:  
1. Unstaged changes: while an operator is proposing a draft, or a user is manually editing, the changes are simply in the file system, and can easily be discarded to the previous committed or stage state.
2. Staged: Staged changes are completed operators, and are ready to be committed, although multiple operators are often ran before a commit. This is like doing something in a game but not reaching a checkpoint; you can still reset to a known spot.  
3. Committed: after a checkpoint is triggered, the changes are bundled in a git commit, pushed to origin, and are now persistent (and cloud backed up!).

## Architecture

Lens is purposely simple, and it's designed to be a stateless script. It just needs to have a file system mount, be pointed to a content repo, and have credentials to push to the repo's origin and config/credentials to connect to an OpenAI-compatible chat completion API endpoint. That's it: the server could have a lifecyle only around a single git commit. It may be a good fit for a fly.io sprite or the like.

When using Lens, at the very minimum the user can do three things:  
  1. Browse, read, and manually edit markdown files. Lens is not needed at all for this, as long as the user follows the structural rules of the storage system. Because we mostly rely on file system for uniqueness and such, this is mostly self-enforcing! The user could make these changes from anywhere, then push what they change.  
    - The knowledge system is reasonably specialized with its tags, so early on we'll want to create a CLI for manipulating these objects.
  2. Apply operators. Because most operators execute at the cursor, they are trivial to invoke, e.g. `lens write "introduce a suspicious vendor" -pin npc.forgery_guy`; the operator then changes a file on disk that the user can just look at or even modify; they can also change their mind `lens undo` or see if the AI has a better outcome a second time by saying `lens retry`, since the context is unambiguous.  
    - In order for this to work, lens has to be configured, of course, meaning a poe project needs to be activated and an LLM configured. We can do this by simply running lens from within the root of our project, which is identified as such by having a `lens.toml` file, created by `lens init`. Since each lens repo can have multiple narrative trees, one can be selected with `lens use my-slug`, which sets it as the current narrative in `lens.toml`.
    - The `lens.toml` file should not have credentials in it, of course, but it can say the env var names to look for those instead; we assume the current shell environment is authenticated in git
  3. Stage, commit, and push changes; `git` does this.

This is good for development (or developers), but does not scale to, say, using Lens on your phone. To do that we need a more full-featured server allows an UI to do the file browsing and editing, as well as the git operations. 

## Lens App (Future)

Ultimately, Lens should have a simple, text-centric UX that's like a "markdown editor with commands". A web UI somewhat similar to Claude Code may work well:
 - Most of the UI is about authoring or previewing markdown files.
 - At the bottom, a command strip that can navigate (replace main UI with results or a tree matching the file system), enter editing mode, or call operators.
   - For example we are running the simulation, and I can just say `/write "introduce a suspicious vendor" -pin npc.forgery_guy` and it will generate and run that write operator with that extra pin
   - You also need to be able to mark begin/end of text for creating sections, being able to zoom in and out of sections, etc. so something like `/section my-aside 123-133` those being line numbers, but after you write `/section my-aside` the UI lets you go to the doc and mark the start and end 
   - Lifecyle features like committing a checkpoint, like `/commit went shopping and found a forger`
 - Sufficiently user friends with hints, auto-complete, and works well on a phone... maybe not as much typing if you can just tap on things 
