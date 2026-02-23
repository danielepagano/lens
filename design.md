# Lens - The Design

> What is it: filesystem-native, forward-only narrative trees and a knowledge store that enable modular AI-assisted creation with fractal summarization.

## Narrative Simulations

Lens is a system that allows users and AIs to collaboratively create "narrative simulations". A Narrative Simulation is essentially prose text, but generated using improvisational elements. They have following properties:  
  1. Narrative is created in a forward-only fashion: once committed, it's canon. It's always technically possible to change the past (it's your story, your data), but the system supports this in very limited ways.
  2. Narrative is grounded by a knowledge store with arbitrary facts. Facts CAN change over time, and are used to both ground the narrative to get things started (lore, rules, etc.) and to track what has transpired
  3. Human user and AI collaborate on writing using an extensible set of operators that allow various simulations and behaviors. An operator is a function to generate or edit text or structure.
  4. The story is hierarchical and fractal. The top level reads like a very high-level overview of what happened so far, but each item within may just be a summary: you can zoom in on these summaries to see the more story detailed story of how that text came to be, which in turn may be a series of summaries, and so on to whatever level of detail you want. This has two goals:  
     1. AI prompts use ancestor summaries at increasingly high level, maintaining high-level continuity with lower resolution for farther away facts; this is like rendering fewer triangles for geometry far away.
     2. You can use the finer details to simulate systems that generate these outcomes, which can be any operator you design, from randomness to an RPG (played within Lens, or outside of it). In other words, this can help Lens be a virtual DM of sorts

## Operators

Operators manipulate text and structure, and can be controlled by parameters.
They may not be one-shot, instead generating output in multiple stages, possibly with refined directions over time. They have the ability to present iterable in-memory drafts before the change is committed to disk. Once an operator is completed and committed, we say it's "closed"

There are several built-in core operators:

 - `write` generates new text to put in a new place. It can use context text or instructions on which directions to take. This can be used to move narrative forward, but also to generate knowledge, maybe using a template. Of course humans can also write directly.
   - The operator can be called multiple times to try again, or to append additional content to the original response, before it is closed. It is also normal for a human to be able to manually edit the response before it is committed.
   - The usage of this operator (and many others) is tracked in the parent node using a comment block to track that it was triggered, and how
 - `summarize` summarizes existing text (optionally with instructions on what to emphasize or ignore) to store it in another place (a less-detailed node, a knowledge item, etc.)
   - Summaries are critically important to maintaining the correct continuity over time, so the prompts used can be heavily curated, and the results manually tweaked.
- `edit` makes targeted changes to a contiguous text selection using AI (for example, to shorten or correct something). It can also summarize, but the point is that it replaces text, it doesn't put its output in a new place.  
    - Unlike other operators, this is a destructive operation (previous version would be in git history). Note the that users can always edit any file themselves (original or summaries) since they are just markdown files; this is  an AI-assisted version of that.
 - `section` lets the user create a child node with its own content, which later will be summarized in the current node; in other words, it breaks narrative into sub-sections, like for chapters and scenes. When the section is over, the user closes the operator, which summarizes the content and moves the narrative up to the parent level
    - Users can also create sections after the fact by selecting a contiguous section of node text, summarize it, and place the original text inside a sub-node as the original source (as if section had been called before text creation). This has to also shift any sub-nodes in the selected range one level down, as the text being selected could already be summaries! Sectioning after the fact is a more complex operation with file/folder movements (captured in git history), but it's necessary since we don't know want the user to always be worried about chapters: they should be able to always keep adding, then later compressing sections (like a conversation or an aside) after the fact.
    - In order to properly separate the section summaries and link them with their expansions, a section  
- `remember` integrates selected aspect of given narrative text into a new or existing knowledge object. 
  - For example, one could be talking with an NPC and then ask the remember that person in `person.name`: the operator looks at the person template to see what kind of facts this knowledge item tracks, and then gathers what we learned into that object, either by creating it or integrating knowledge. 
  - You could remember the same chunk of narrative into multiple objects, for example a location as well, and only the location details would be relevant to the second item. The AI uses the template to extract only the relevant facets on each remember operation.
  - Later recalling what is remembered is already done by the text generation operators by proving them the IDs of the relevant objects to know about. 

Operators are designed to be extended, and more can be created as specializations or hybridizations of the core operators; these allows more specific ways to manage content and interact with the narrative. Examples of operators that could be added:
  - `play` could be like write, but has knowledge of who the player and non-player characters in the story are. It generates text in a way that delegates agency to the player characters (does not write what they think, feel, decide, or do), giving the user the space to make those decisions.
    - The opposite could also be true, where the user asks the AI to "play as" as character (autonomously or with direction). This allows the user to be the DM and/or players, maintaining that role isolation in the narrative beats. 
  - `dnd` could be even more specialized than `play` (or be a family of operators), having the user have player characters merely attempt difficult actions, and having a conversation with the AI on what checks could be used (e.g. "Roll a stealth check to try to sneak by the guards"); the human could then roll dice and use RPG character sheets of their player characters; the AI then makes a determination of level of success and moves the narrative forward accordingly. The whole exchange would be in a node, the checks and rolls would be there, but only the result would be part of the narrative (specialized summary)
  - `chat` could spin up an agentic chat in a sub-node to talk about the current going on's. This can be used for fun ("that was crazy!"), to explore the feeling of characters off the page (maybe then by remembering the results), to plan what happens next, etc. This would be all non-canonic narrative, but still contextually kept in the simulation tree.
  - `attach` could allow you to attach media within a node 

## High-level filesystem layout

Each Lens project is a git repo (not the app's repo, but a content repo you point the app to).
The repo acts as your database and also lets you literally read Markdown files for the story you wrote, while tracking progress over time and even allowing you to  create "alternate universes" or explore "what-if scenarios" using git branches.

A Lens project has two main areas:  
 - Knowledge: the grounding facts that inform your narrative (rules, lore, accumulated history, etc.)  
   - Each knowledge item has a type, unique id within that type, content, and tags (used to search/link items)
 - Narrative: the narrative simulations you want to run (books or adventures in your world)  
   - A unit of narrative is a "node", which is either a markdown file, or a folder with `_node.md` file, plus child files and folders. The node is the canon text, which can be split into multiple section, with an id, managed by operators, and backed by a sub-node (file or folder).

A project has the following structure:

```
/<project-root>/
  narrative/
    <simulation-slug>/  <-- you can run multiple parallel simulations for the same knowledge set
      _node.md          <-- the canon text and any operator applications
      event_1/          <-- the source node for the parent's section with this id
        _node.md        <-- node content
      event_2.md        <-- shorthand for event_2/_node.md if recursion not needed
  knowledge/
    _tags.toml         <-- an index of all tags and the object ID's that have that tag (python dicts) 
    npc/               <-- the object type
      _template.md     <-- optional template for that object type (helps consistent structure/LoD)
      forgery_guy.md   <-- filename is object key, file content is object content
    place/
      needle_street.md
```

Design:

* A node contains any markdown, and it's supposed to be readable and complete _at that level of detail_.
* Internally, nodes are annotated and section using invisible [comments](https://www.markdownguide.org/hacks/#comments) in the form of `[content]: #` and they have to appear on their own line and have an empty line before them; if multi-line, they have to be indented. Examples:

```markdown
[
  op:write
  prompt: hey you! how about a \
multiline prompt here?
  kb_pins: 
    - first 
    - second
]: #

This was written by the op:write above, which you can't see, but it's good to know!

[/op:write]: #
This was added by hand! It's good to know when the AI was done.

[section:my_elaborate_aside]: #

This looks like it goes right after the above, but it's a summary of an elaborate aside in a child node called `my_elaborate_aside`!

[/section:my_elaborate_aside]: #

Now we're just adding content to the original node!
```

* The knowledge storage format is very simple:  
  - An object id is its type (directory name) plus key (file name minus `.md`). Its contents are the full content of the `.md` file. Comments can be used to add details that should be excluded when referenced.
  - A template is just an object with a reserved key, used by the UX
  - The `_tags.toml` file is a dictionary of string (tag) to set of strings (object id's with that tag)

# Example node (`my_node.md` or `/my_node/_node.md`

```markdown
[ <-- invisible "front matter" section for global settings
  kb_pins: <-- knowledge-aware operators always add this content, even in child nodes!
    - place.needle_street
    - place.capital_city
  kb_unpin:  <-- you can un-pin irrelevant parent pins from this sub-tree
    - front.the_demon_rises 
]: #
You enter the market at noon, carts clattering.

[
  op: write  <-- the slug of the operator to use
  prompt: introduce a suspicious vendor   <-- this is an argument used by the write operator
  kb_use:    <-- this is a KB operator, so it reads pins and allows adding additional knowledge
    - npc.forgery_guy
  kb_unpin:  <-- you can also temporarily remove irrelevant content from this operator invocation
    - place.capital_city 
]: # 
A shady-looking vendor is at the second stall, looking over his wares you see... 

[section:market_fence_vendor]: #
You find out the vendor is a fence; he gives you a discount when you discover this, and agree to keep your mouth shut.

[/section:market_fence_vendor]: #
You continue your day...
```

Node rules:
- operators can define what front matter works and what it does. The knowledge system defines `kb_pins` and `kb_unpin'
- Everything visible in rendered markdown is canonical narrative for that level of detail; operators that look at content skip over comments

## Context-aware operator prompt assembly

When you invoke a context-aware operator, the engine uses fractal summarization and knowledge insertion to create a prompt that tries to maximize contextual knowledge. This prompt includes:

- **System instructions** (operator-specific system prompt; usually static).
- **Collected knowledge expansions** (all KB items pinned or added, deduped, in priority order from nearest node to farthest ancestor).
  - Any comments in knowledge are also skipped by this inclusion: this allows the items to have drafts or notes (for example desired character milestones) without the AI pulling them into the prompt as if they were facts.
  - Because knowledge items are meant to mutate, calling the same operator with the same knowledge over time will have different results! Using git allows us to know when this operator was called, and thus what the knowledge state was at the time.
- **Ancestor narrative** (root → parent), content of each parent node (always strip comment blocks). 
  - These are a "zoom-out" values, so usually summaries. So if you are 3 levels in, let's say semantically you have chapter, scene, and beat, and you hare in chapter 3, scene 4, beat 3, the ancestor narrative includes the chapter 1 and 2 summaries, chapter 3 scene 1-3 summaries, and scene 4 beat 1-2 summaries. Because we write forward only, this, in practice, just means the full text of all parent nodes (minus any comments)
- **Current node narrative**. The narrative text before this operator in this node, if any.
- **Instructions based on operator and its configuration** (in natural language, for example the `write` operator has a `prompt` string telling the AI to continue writing in a certain direction, while a `summary` operator tells the AI to summarize the "Current node narrative").

## Data Lifecycle

There are three persistence levels:  
1. Memory: while an operator is proposing a draft, or a user is manually editing, nothing is written to disk yet
2. Uncommitted: data is saved to disk, but not committed to git repo yet
3. Committed: after a checkpoint is triggered, the changes are bundled in a git commit and are now persistent; the commit can then be pushed to a private repo for resilient cloud storage

## Architecture

Lens is purposely simple, and it's designed to be a stateless script. It's really a stateless script that just needs to be pointed to a repo, and a way to find credentials to push to an origin (its entire long-term storage), and config/credentials to connect to an OpenAI-compatible chat completion API endpoint. That's it: the server could have a lifecyle only around a single git commit, and it only has transient UI state to do with reviewing content and changes before they are saved to disk. It's a good fit for a fly.io sprite or the like.

## UX

Lens should have a simple, text-centric UX that's like a "markdown editor with commands". A web UI somewhat similar to Claude Code may work well:
 - Most of the UI is just a markdown file, being either rendered or authored
 - At the bottom a command line that can navigate (replace main UI with results or a tree matching the file system), enter editing, or call operators.
   - For example we are running the simulation, and I can just say `/write introduce a suspicious vendor -pin npc.forgery_guy` and it will generate and run that write operator with that extra pin
   - You also need to be able to mark begin/end of text for creating sections, being able to zoom in and out of sections, etc. so something like `/section my-aside 123-133` those being line numbers, but after you write `/section my-aside` the UI lets you go to the doc and mark the start and end 
   - Lifecyle features like committing a checkpoint, like `/commit went shopping and found a forger`
 - Sufficiently user friends with hints, auto-complete, and works well on a phone 
