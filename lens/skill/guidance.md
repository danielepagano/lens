# Working in a Lens project

This is a Lens project: a git repository with a `lens.toml`, a `narrative/` tree
of prose, and a `knowledge/` store of small addressable objects. AI operators
(`write`, `play`, `design`, …) assemble their prompts from the knowledge store
plus the narrative above the cursor. What you leave behind is what they read.

Git's unstaged area is the pending transaction. `lens commit` stages it (a
transaction boundary, not a git commit); `lens checkpoint "message"` commits and
pushes. Leave one coherent, reviewable change and say what you changed.

What follows is what no `--help` tells you: the conventions that fail
*silently*. For everything else, ask the command that owns it:

- what can run here — `lens --help` (dataset gating applied), then
  `lens <command> --help`
- types, counts, narratives, pins at the cursor, model-requestable modules —
  `lens stats`
- tags — `lens kb list-tags`; design modules — `lens kb list --type design`;
  local forks of dataset objects — `lens kb list --shadowed --source project`
- a dataset's full conventions — `lens skill <dataset>`, named below

## Reading what a model reads

A node file is not the story. A model is given the **spine**: every node from the
narrative root down to the cursor, each ancestor contributing its prose (its
summary, once collated) and only the cursor node its live text. `lens spine`
prints it as the prompt renders it. Read it before adding anything:
contradicting what an ancestor established is the expensive mistake.

`lens explain -o <operator>` assembles the prompt a cursor would get, without
calling a model: every component's size and the route it arrived by (`--json`
answers "why is X in the prompt, or not"), or with `--messages` the text itself.
**Pass the operator** — `write` and `play` resolve different sets at the same
cursor. A line argument rebuilds the prompt as of that line: `lens explain -o
play . <line above a beat's open tag>` is what that beat was generated from.

That is how to check a change. **The diff is not the artifact; the assembled
prompt is** — no test asserts on what a KB or prompt edit does to a model's
input. Verify with a fresh `lens` command, not a process left running: the tag
index is cached per process, and a stale one makes a `+` expansion silently
resolve to nothing.

## Node files

A node is markdown the next beat reads back, and hand-editing its prose is
fine. The rest of the file is not prose:

- **`[op …]: #` and `[/op]: #` lines are operator tags.** The cursor is the last
  unclosed one at the tail of the file, so moving or deleting one moves the
  cursor, or closes or reopens a session.
- **Every `[…]: #` line is invisible to models.** `[llm-trace …]: #` is
  diagnostics and safe to delete; `[kb-op …]: #` is a pending KB proposal, and
  deleting it withdraws it; `[include: <id>]: #` and `[mention: <id>]: #` add
  scope (below).
- **`<!-- … -->` comments are the opposite:** hidden when rendered, but read by
  every later generation at that node — `ai:secret` ones decoded first.

**Hand edits join the pending transaction, and `lens rollback` discards every
unstaged change in the repository** — yours included, untracked files too. Run
`lens commit` after your own edits to keep them. To redo a beat: `lens
<operator> --retry` regenerates the last generation, `lens edit` rewrites a line
range, and `lens rewind <address> <line>` deletes everything after a point.

## What fails silently

**1. `knowledge/` is not the knowledge store.** The store merges this project's
tree with every active dataset's, and datasets resolve *outside* this repository,
so `grep -r` misses them. Use `lens kb search PATTERN` (regex over ids, types,
tags and bodies; `id:line:text`), `lens kb list`, and `lens kb get <id>`. Their
`SOURCE=` field says which store won and what it shadowed.

**2. Editing a dataset file edits it for every project using that dataset.**
Write through `lens kb add <id> '<content>'` (an upsert of the whole body): it
always writes into *this* project, forking a local copy on first write. Only a
file already under this repository's `knowledge/` is safe to edit directly.

**3. Tags live in `knowledge/tags.toml`, not in the object files.** A
hand-written `knowledge/rules/x.md` has no tags and no index entry — invisible to
tag lookups and `+` expansion. Use `lens kb tag <id> -a <tag>`. A *dot-tag*
(`person.amy`) is a link to that object; `lens kb refs <id>` reports links in
both directions, including references that never name the id.

**4. A type is a tag.** A bare type name (`design`, `rules`) matches every object
of that type, unioned with the tag index; that is how operators discover modules
and rulesets. A new object of an existing type is discoverable the moment it
exists, and a new *type* is a bigger decision than it looks.

**5. An object's first three lines are its self-description.** Every listing
prints them under each match, and a dataset-registered module uses them *as* its
catalog entry — with no headline it is not offered at all. Open with what the
object is and when it matters.

**6. Guidance is paid at different rates.** A `rules.*` booklet is paid on
*every* beat with an object of its type in scope, under every operator; a
`design.*` module once per design session; an ordinary object only when in
scope. Adding to a booklet is the expensive edit, and booklets are already most
of a play prompt. Cut whole rules rather than diluting the ones you keep:
numbers and thresholds must survive verbatim.

**7. `lens kb get` can show what is not on disk.** While a `design` or `advance`
session is open at the cursor, its proposed writes are a layer every read sees
(`SOURCE=pending`), but nothing reaches `knowledge/` or git until `--end` — a
clean `git diff` beside a changed store. `lens kb pending` lists them.

## Scope: what a model actually sees

Knowledge reaches a prompt by explicit scope, never by existing — **a tag is not
scope.** A dot-tag makes an object reachable *if something expands it*; on its
own it puts nothing in front of a model, which in the repo looks identical to
material that works. `lens explain` tells them apart.

- **Pins** (`kb_pin` / `kb_unpin` in front matter; `lens pin kb add <id>`)
  inherit root to cursor. `<id>+` expands dot-tag links; without the `+`, easy
  to leave off, the object comes alone.
- **Includes** (`[include: <id>]: #`) last the rest of the node; **mentions**
  (`[mention: <id>]: #`, or `@type.key` in a prompt) last one turn. Both expand
  in place and are not inherited by sub-nodes.
- **`state`-tagged objects** render at the tail, next to the task. Anything a
  person updates mid-session belongs there; up front it would invalidate the
  prompt cache on every edit.

## Names the engine reserves

Matched by name alone in every project, whatever the datasets, so a near miss is
simply never delivered:

- **`rules.<type>`** — the companion: how to *use* a `<type>.*` object. Whenever
  one is in scope, by any route, the companion comes along, for every operator.
  Never link it with a tag. The expensive place to write (rule 6).
- **`<type>._template`** — how to *create* one. Read when an object is created
  from it, when a design module resolves it, and by the remember pass for format
  hints. Its front matter may declare default tags.
- **`remember.<key>`** — as a *tag* on a pinned object, makes that object a
  target of the remember pass at summarize boundaries; the tag's own id names the
  object holding the instructions.
- **`design.<key>`** — a Session Zero module, run with `lens design --module
  <key>`; fetching it also returns `<key>._template`.

The reserved tags are `state` (above) and `inline` (an `@type.key` mention of the
object is replaced by its body instead of a reference). Everything else —
`rules.system`, `meta.*`, `pc.*` — belongs to a dataset.
