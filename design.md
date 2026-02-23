# Lens - The Design

> What is it: filesystem-native, forward-only narrative trees and a knowledge store that enable modular AI-assisted creation with fractal summarization.

## Narrative Simulations

Lens is a system that allows users and AIs to collaboratively create "narrative simulations". A Narrative Simulation is essentially prose text, but generated using improvisational elements. They have following properties:  
  1. Narrative is created in a forward-only fashion: once committed, it's canon. It's always possible to change the past (it's your story, your data), but the system supports this in very limited ways.
  2. Narrative is grounded by a knowledge store with arbitrary facts. Facts CAN change over time, and are used to both ground the narrative to get things started (lore, rules, etc.) and to track what has transpired
  3. Human user and AI collaborate on writing using an extensible set of operators that allow various simulations and behaviors. An operator is simply a mechanism to generate or edit text.
  4. The story is hierarchical and fractal. The top level reads like a very high-level overview of what happened so far, but each item within may just be a summary: you can zoom in on these summaries to see the more story detailed story of how that text came to be, which in turn may be a series of summaries, and so on to whatever level of detail you want. This has two goals:  
     1. AI prompts use ancestor summaries at increasingly high level, maintaining high-level continuity with lower resolution for farther away facts; this is like rendering fewer triangles for geometry far away.
     2. You can use the finer details to simulate systems that generate these outcomes, which can be any operator you design, from randomness to an RPG (played within Lens, or outside of it). In other words, this can help Lens be a virtual DM of sorts

## Operators

There are several built-in core operators:

 - `author`: generates text using other contextual text, plus instructions, using AI. This can be used to move narrative forward, but also to author knowledge, maybe using a template
 - `summarize`: summarize existing text to store it in another place
 - `zoom`: lets the user create a child node with its own text, which later will be summarized in the current node; in other words, breaks narrative into sub-sections on purpose, like for chapters and scenes. When the section is over, the user "closes" the operator, which summarizes the content and moves the narrative back up to the parent level
 - `group` this is a "zoom after the fact": it take a contiguous selection of node text, summarizes it, and puts the original text inside a sub-node as the original source (as if zoom had been called before text creation). Grouping can be performed in the middle of a node, which may change subsequent operators indices, so some file/folder renaming may be needed (captured in git history)
 - `edit`: makes targeted changes to a contiguous text selection using AI (for example, to shorten or correct something); unlike other operators, this is a destructive operation (previous version in git history). Note the that users can always edit any file themselves (original or summaries); this is just an AI-assisted version of that.

Operators are designed to be extended, and more can be created as specializations of the core operators; these allows more specific ways to manage content, for example an author that asks multiple interactive questions to to the user could effectively be a Game Master that simulates asking the player to have a character inside the story to roll dice to determine what happens. When this operator is "closed", the result wouldn't be the summary of all interactions, just the result of action.

## High-level filesystem layout

Each Lens project is a git repo (not the app's repo, but a content repo you point to).
The repo act as your database and also lets you literally read Markdown files for the story you wrote, while tracking progress over time and allowing you to even create "alternate universes" or explore "what-if scenarios" using git branches.

A Lens project has two main areas:  
 - Knowledge: the grounding facts that inform your narrative (rules, lore, accumulated history, etc.)  
   - Each knowledge item has a type, unique id within that type, content, and tags (used to search/link items)
 - Narrative: the narrative simulations you want to run (books or adventures in your world)  
   - Each level of narrative has a `_node.md` which is the canon text, which can be split into multiple steps, each linked to a different operator, and each step can have its own sub-node or recursive sub-folder

A project has the following structure:

```
/<project-root>/
  narrative/
    <simulation-slug>/  <-- you can run multiple parallel simulations for the same knowledge set
      _node.md          <-- the canon text and any operator applications
      001/              <-- the source node for the parent's section at this index
        _node.md
      003.md            <-- numeric child file (shorthand for 003/_node.md); note that 002 has no sub-file, meaning it's not a summary; this normal, it's a sparse graph
      004_for_market.md <-- cosmetic suffix allowed for human consumption, value after _ is ignored by indexing
  knowledge/
    _tags.toml         <-- an index of all tags and the object ID's that have that tag (python dicts) 
    npc/               <-- the object type
      _template.md     <-- optional template for that object type (helps consistent structure/LoD)
      forgery_guy.md   <-- filename is object key, file content is object content
    place/
      needle_street.md
```

Rules:

* Every narrative container (folder or numbered file) has a canonical `_node.md` content. It contains any markdown
  * Nodes may contain front matter with embedded YAML to establish node-wide operator configuration; in particular object keys can be pinned to each node to be included in the request context of all  operators downstream from this node
* Inside a node, you can enter a fenced code section of type `operator`, which triggers an operator, with the text after it being the operator's output (until the next operator); this splits the file into up to 1000 sections.  
  * Section `000` is anything before the first operator.
  * If an operator generates a sub-node, the output at the level of its request will be summary of that node. While the operator is running, the text will just be the placeholder text `> operator resolving...`.
* The knowledge storage format is very simple:  
  - An object id is its type (directory name) plus key (file name minus `.md`). Its contents are the full content of the `.md` file
  - A template is just an object with a reserved key, used by the UX
  - The `_tags.toml` file is a dictionary of string (tag) to set of strings (object id's with that tag)

[Example `_node.md`]
---
kb_pins: <-- knowledge-aware operators always add this content, even in child nodes!
  - place.needle_street
  - place.capital_city
kb_unpin:  <-- you can un-pin irrelevant parent pins from this sub-tree
  - front.the_demon_rises 
---
<-- beginning of file's content (above is front matter); section 000 begins here
You enter the market at noon, carts clattering.

<-- Becomes an operator follows, here section 000 ends; below is the operator generating section 001
```operator
op: author  <-- the slug of the operator to use
prompt: introduce a suspicious vendor   <-- this is an argument used by the author operator
kb_use:    <-- this is a KB operator, so it reads pins and allows adding additional knowledge
  - npc.forgery_guy
kb_unpin:  <-- you can also temporarily remove irrelevant content from this operator invocation
  - place.capital_city 
````
<-- This is section 001
A shady-looking vendor is at the second stall, looking over his wares... 

[End of example `_node.md`]

Node rules:
- operators can define what YAML front matter works and what it does. The knowledge system defines `kb_pins` and `kb_unpin'
- Everything *outside* triple-backtick operator code blocks is canonical narrative; normally, operators that look at content skip over these
- All machine-consumable inputs and non-canon text are fenced code blocks
  - Use the fence tag `operator` for inputs. The content of an `operator` fence **must** be YAML, and contain at least one value: `op:<string>` (rest depends on operator)
  - Other operators may create fenced code blocks of other types to interact with the user without generating canon, for example to ask them to select from options or have them roll dice. More often, they may just create a sub-node and use custom prompt-building and summarization to achieve this result.

## Context-aware operator prompt assembly

When you invoke a context-aware operator, the engine uses fractal summarization and knowledge insertion to create a prompt that tries to maximize contextual knowledge. This prompt includes:

- **System instructions** (operator-specific system prompt; usually static).
- **Collected knowledge expansions** (all KB items pinned or added, deduped, in priority order from nearest node to farthest ancestor).
- **Ancestor narrative** (root → parent), content of each parent node (always strip fenced code blocks). 
  - These are a "zoom-out" values, so usually summaries. So if you are 3 levels in, let's say semantically you have chapter, scene, and beat, and you hare in chapter 3, scene 4, beat 3, the ancestor narrative includes the chapter 1 and 2 summaries, chapter 3 scene 1-3 summaries, and scene 4 beat 1-2 summaries. Because we write forward only, this, in practice, just means the full text of all parent nodes (minus any placeholders, front matter, and operator instructions)
- **Current node narrative**. The narrative text before this operator in this node, if any.
- **Instructions based on operator and its configuration** (in natural language, for example the `author` operator has a `prompt` string telling the AI to continue writing in a certain direction, while a `summary` operator tells the AI to summarize the "Current node narrative").

## Data Lifecycle

There are three persistence levels:  
1. Memory: while an operator is proposing a draft, or a user is manually editing, nothing is written to disk yet
2. Uncommitted: data is saved to disk, but not committed to git repo yet
3. Committed: after a checkpoint is triggered, the changes are bundled in a git commit and are now persistent; the commit can then be pushed to a private repo for resilient cloud storage

## Architecture

Lens is purposely simple, and it's designed to be a stateless script. It's really a stateless script that just needs to be pointed to a repo, and a way to find credentials to push to an origin (its entire long-term storage), and config/credentials to connect to an OpenAI-compatible chat completion API endpoint. That's it: the server could be created only around a single git commit, and it only has transient UI state to do with reviewing content and transient file changes before a commit. It's a good fit for a fly.io sprite or the like.

## UX

Lens should have a simple, text-centric UX, with facilities to edit and render Markdown, find and manage knowledge objects, navigate the narrative trees, and fill in operator parameters, which should be as simple as possible. Creativity can happen at any time, so it should have a web interface that works equally well on a laptop and on a phone.
