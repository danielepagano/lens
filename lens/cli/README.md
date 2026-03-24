# CLI reference

Full reference for Lens commands, the knowledge store, pins, sections, AI operators, and LLM configuration.

## Usage

1. Create a git repo for your project and `cd` into it.
2. Initialize the Lens project (creates `lens.toml`, `knowledge/`, `narrative/`, etc.):

   ```bash
   lens init
   ```

3. Select a narrative (creates the folder and root `_node.md` if needed):

   ```bash
   lens use my-campaign
   ```

4. Run lens commands:

   ```bash
   lens stats      # count objects and list narratives (-v for transaction diffs)
   lens kb         # knowledge store (see lens kb --help)
   lens section    # start or end a section at cursor
   lens collate    # crete a section after the fact from completed prose
   lens pin        # pin/unpin knowledge objects to nodes (see lens pin --help)
   lens write      # AI: generate narrative text at the cursor
   lens edit       # AI or manual: rewrite/replace a selected line range in narrative
   lens rewind     # move the cursor back to a node or line, deleting what comes after
   lens rollback   # discard or compensate a pending operator transaction
   lens commit     # stage all changes (git add -A)
   lens checkpoint # stage, commit, and push; optional message and --no-push
   lens refresh    # fetch and fast-forward from remote; --reset to match remote exactly
   ```

Dataset-gated commands (e.g. `lens dnd`) and operators (`play`, `advance`) appear only when their dataset is listed in `[project] datasets`. See [RPG](../rpg/README.md) and [D&D](../dnd/README.md).

## Project commands

### `lens init`

Initialize a Lens project in the current git repo. Creates `lens.toml`, `knowledge/`, `narrative/`, and sets the active narrative in the config. Requires an existing git repository.

### `lens use <slug>`

Select the active narrative. *slug* must be alphanumeric with optional underscores and hyphens. Creates the narrative folder and root `_node.md` if they do not exist.

### `lens stats`

Count knowledge objects by type and list narrative trees with node counts. Shows the active narrative cursor and whether an open transaction exists (and its owner).

- `-v` / `--verbose` — Print pending transaction diff (unstaged) and staged (checkpoint) diff.

### `lens commit`

Stage all changes in the project (`git add -A`). Use this to “commit” the current transaction so it becomes part of the next checkpoint.

### `lens checkpoint [MESSAGE]`

Stage all changes, create a git commit (with *MESSAGE* or a default timestamped message), and push to the remote if one is configured.

- `--no-push` — Create the commit but do not push.

### `lens refresh`

Fetch from the remote and fast-forward the current branch to its upstream (no merge commits). Requires a clean working tree unless you use the destructive option.

- `--reset` — After fetch, reset the branch to match the upstream exactly. Discards unpushed commits, uncommitted changes, and untracked files. Use when a normal refresh or checkpoint cannot proceed (for example, the remote moved forward and you need to align with it).

### `lens rewind`

Move the cursor to an earlier point in the narrative, deleting everything after it.

```bash
lens rewind /chapter-1          # rewind to the end of chapter-1 (cursor moves there)
lens rewind /                   # rewind to the narrative root
lens rewind /@cursor            # clean up open tail at the current cursor (no-op if clean)
lens rewind /chapter-1 42       # rewind to line 42 within chapter-1
```

Arguments: `ADDRESS [LINE]`

- `ADDRESS` — narrative node to rewind to (e.g. `/chapter-1`, `my-story/chapter-1`).
- `LINE` — optional 1-based line number within the node.

**Node-level rewind (no line number):** The cursor is placed at the end of `ADDRESS`, deleting everything that comes after — later sibling sections (their summaries, close tags, and child nodes), and any unclosed section at the tail of `ADDRESS` itself. If the target is already the cursor position and its tail is clean, this is a no-op.

**Line-level rewind:** The node's file is truncated at `LINE` with structural adjustments:

| Line position | Behaviour |
|---|---|
| Front matter | Node is cleared entirely (empty file) |
| Inside an opening annotation tag | Annotation and everything after is deleted |
| On or in a closing annotation tag | Everything after the tag is deleted; tag is kept |
| Inside a section's summary body | Entire section block + its child node are deleted |
| Inside a write/edit body | Body truncated there; close tag moved to that position |
| Free text | Simple truncation |

In all cases, child nodes whose section annotations are no longer present are recursively deleted. Side effects such as KB objects created by `design` are never modified. The changes are left as a pending transaction; use `lens commit` or `lens checkpoint` to keep them.

### `lens rollback`

Discard the pending transaction. For inline operators (e.g. `write`), reverts unstaged changes. For mutation operators (`edit`), applies a compensating transaction (removes claim tags and restores original text). Prompts for confirmation unless `-y` / `--yes` is given.

## Knowledge store (`lens kb`)

| Command    | Purpose                          |
|-----------|----------------------------------|
| `add`     | Create or update objects         |
| `edit`    | AI: edit or create objects      |
| `extract` | Bulk-import objects from a structured markdown file |
| `get`     | Fetch objects (append `+` for directly linked, `++` for full tree traversal) |
| `list-tags` | List unique tag values, optionally by type or prefix |
| `with-tag`| List/expand objects by tag; optionally recurse via dot-tags |
| `template`| Manage type templates            |
| `tag`     | Add/remove tags on objects       |
| `delete`  | Delete object and its references |
| `copy`    | Copy object to a new ID (any type) |
| `rename`  | Rename object to a new ID (any type) |

Run `lens kb <command> --help` for details. All KB IDs and tags normalize to lowercase.

### `lens kb add`

Create or update a single knowledge object.

```bash
lens kb add person.hero "A seasoned adventurer."
lens kb add location.inn -t   # create empty or from type template
```

Arguments: `ID [CONTENT]`

- `ID` — object ID (e.g. `person.hero`). Required.
- `CONTENT` — object body. Omit for an empty object or to no-op if unchanged.

Options: `-t` / `--use-template` — use the type’s template content (from `_template.md`) when creating.

### `lens kb get`

Fetch and print knowledge objects. Append `+` to an ID to include directly linked objects (via dot-tags); append `++` for full breadth-first traversal of linked objects.

```bash
lens kb get person.hero
lens kb get person.hero+ place.tavern++
lens kb get person.hero --no-include-comments   # strip markdown comments
```

Options: `--include-comments` (default: true) — keep markdown comments in the output.

### `lens kb template`

Get or set the template content for an object type (stored as `knowledge/<type>/_template.md`). Omit *CONTENT* to print the existing template.

```bash
lens kb template person          # print current template
lens kb template person "Name, role, description."
```

Arguments: `TYPE [CONTENT]`

### `lens kb tag`

Add or remove tags on an object.

```bash
lens kb tag person.hero --add featured --add faction.rebels
lens kb tag person.hero --remove featured
```

Options: `-a` / `--add` (repeatable), `-r` / `--remove` (repeatable). Dot-tags must reference an existing object; invalid references are reported as a warning.

### `lens kb delete`

Delete an object: removes its file, its tag entries, and references from other objects. For dataset-only objects, this is a no-op (dataset items are immutable).

```bash
lens kb delete person.old-npc
```

### `lens kb copy`

Copy an object to a new ID. The source may be in a dataset (copy is created in the project). Target type may differ; the target directory is created if needed.

```bash
lens kb copy person.hero person.custom-hero
```

Arguments: `SOURCE_ID TARGET_ID`

### `lens kb rename`

Rename an object to a new ID. New type may differ; the target directory is created if needed.

```bash
lens kb rename person.old-key person.new-key
```

Arguments: `OLD_ID NEW_ID`

### `lens kb extract`

Bulk-import KB objects from a structured markdown file in a **single git transaction**. Useful for seeding reference data, importing AI-generated batches, or bootstrapping a campaign from notes.

````bash
lens kb extract objects.md
lens kb extract ./my-notes/   # folder: all .md files processed depth-first
````

The path may be a file or a folder; for a folder, all `.md` files under it (and subfolders) are processed in depth-first lexicographical order. The file(s) may contain any text. KB objects are defined in fenced blocks tagged with `kb`. Each block must have a YAML front matter section (delimited by `---`) with an `id` field and an optional `tags` list. Everything after the closing `---` is the object content. Content between blocks is ignored.

````markdown
# My campaign notes (ignored)

```kb
---
id: person.alice
tags:
  - character
  - faction.rebels
---
Alice is a rebel fighter who joined the cause at age 17.
<!-- ai:secret: She is a double agent. -->
```

Some thinking (ignored)...

```kb
---
id: location.hq
---
The rebel headquarters, hidden in an abandoned warehouse.
```
````

- **Inserts** create new objects; **updates** overwrite existing object content.
- Tags are **additive**: new tags are added to any already on the object.
- Blocks with missing `id` or parse errors are skipped and reported as warnings.
- All writes use a single `Storage` instance — they land as one pending transaction reviewable with `git diff`.

### `lens kb edit`

Edit or create a knowledge object using AI. Works on existing objects (including dataset items — copy-on-write applies) or creates new ones from scratch.

```bash
lens kb edit person.hero "add a dark secret"
lens kb edit person.hero "make them more mysterious" -p place.castle
lens kb edit person.new-npc "describe a weary traveler" -t
```

Arguments: `ID INSTRUCTION`

- `ID` — object ID (e.g. `person.hero`). Creates the object if it does not exist.
- `INSTRUCTION` — AI instructions for what to write or change.

Options: `-p`/`--pin`, `-u`/`--unpin`, `-c`/`--context` (narrative address to crawl for context), `-t`/`--include-template` (include type template in prompt), `-l`/`--llm`. `--context` is not available in dataset mode.

### `lens kb list-tags`

List unique tag values from the knowledge store, optionally filtered by object type or tag prefix.

```bash
lens kb list-tags                           # All tags
lens kb list-tags --type stat               # Tags on stat objects only (-t)
lens kb list-tags --start-with cr:          # Tags starting with cr: (e.g. cr:1, cr:2) (-s)
lens kb list-tags -t stat -s cr:            # CR tags on stat objects
```

Options: `-t` / `--type` (object type), `-s` / `--start-with` (tag prefix).

### `lens kb with-tag`

Back-traverse the tag index to see which objects have a given tag, and optionally walk "up" a location/map hierarchy.

```bash
lens kb with-tag location.kingdom                # IDs of objects tagged with location.kingdom
lens kb with-tag location.kingdom -e             # Print full objects instead of IDs
lens kb with-tag location.kingdom -r             # Breadth-first over dot-tags (e.g. kingdom → cities → taverns)
lens kb with-tag location.kingdom -r -e          # Same as above, but print objects layer by layer
lens kb with-tag location.kingdom -r -e -s       # Only follow/print IDs whose type matches the starting tag (location.*)

# OR groups: use (a b c) for tags that match any of a, b, or c. Quote for shell:
lens kb with-tag "(cr:1-2 cr:1-4)" "(type:undead type:humanoid)" size:large
```

- Base form prints object IDs with their tags (e.g. `stat.ghoul  [cr:1 type:undead]`).
- **OR groups**: Tags in `(a b c)` match objects that have *any* of those tags. Groups are ANDed; quote parenthesized args for the shell.
- `-e/--expand` prints objects in the same `KB['id']` format as `lens kb get`.
- `-r/--recurse` follows dot-tags from objects (and object IDs used as tags, e.g. for Up-style location maps) breadth-first, avoiding cycles. Optional numeric argument limits depth (e.g. `-r 2`); `0` means full traversal.
- `-s/--same-type` filters by object type when the starting tag is a dot-tag: root IDs and recursive layers include only IDs whose type matches. For non-dot tags, `-s` is ignored.

## KB Datasets

Datasets are read-only knowledge stores bundled with the Lens tool. They let you share common knowledge — rules, templates, world-building lore — across many projects without copying files into each one.

### Importing a dataset

Add a `datasets` list to the `[project]` section of your `lens.toml`:

```toml
[project]
narrative = "my-campaign"
datasets  = ["testing"]          # one or more dataset names
```

Datasets are resolved in order: **later entries shadow earlier ones**, and **project-local items always win** over any dataset. So you can import a dataset and safely override individual objects by creating a project-local copy.

### Lookup and copy-on-write

When Lens looks up a KB object it searches the project first, then each dataset in the order listed (last wins for conflicts). This means you can `lens kb get`, `lens pin add`, or reference any dataset object exactly as if it were a project-local object — no explicit import step required.

Mutating a dataset object (`lens kb tag`, `lens kb add`, `lens kb edit`, etc.) automatically creates a **project-local copy** first and applies the change there. The original dataset file is never modified.

```bash
# Dataset item "person.hero" becomes visible automatically:
lens kb get person.hero

# Tagging it creates a local copy in knowledge/person/hero.md:
lens kb tag person.hero --add featured

# Explicitly copy a dataset item into the project under a new ID:
lens kb copy person.hero person.custom-hero
```

Deleting a dataset-only object is a **no-op** — dataset items are immutable from the project's perspective. If you previously created a project-local copy of a dataset object, deleting that local copy is allowed (and will reveal the original dataset version again).

### Available datasets

| Name | Description |
|------|-------------|
| `testing` | Minimal dataset used by the Lens integration test suite. |

See [D&D](../dnd/README.md) for the `dnd` dataset.

## Knowledge pins (`lens pin`)

Pins attach knowledge objects to a node's front matter so they are automatically included in AI operator prompts. Unpins cancel pins inherited from ancestor nodes.

| Command    | Purpose                                         |
|------------|-------------------------------------------------|
| `add`      | Add to `kb_pin` (include in prompts)            |
| `remove`   | Remove from `kb_pin`                            |
| `block`    | Add to `kb_unpin` (cancel an ancestor pin)      |
| `unblock`  | Remove from `kb_unpin`                          |

All commands take one positional ID and an optional positional node address (default: cursor). Use `-i`/`--id` (repeatable) for multiple IDs, and `--node`/`-n` when combining with `-i`.

```bash
lens pin add person.amy                            # pin at cursor
lens pin add person.amy /amy-story                 # pin at specific node
lens pin add person.amy test-narrative/amy-story   # full address
lens pin add -i person.amy -i place.city --node /amy-story  # multiple IDs

lens pin block person.amy /amy-story   # suppress an ancestor pin here
lens pin remove person.amy             # undo a pin
lens pin unblock person.amy            # undo a block
```

Node addresses follow the format `[<narrative>/]<key>[/<key>...]` or `/@cursor`. Run `lens pin <command> --help` for details.

## Sections (`lens section`)

Sections structure the narrative tree by creating child nodes under the cursor.

```bash
lens section intro          # create child node "intro" and open section tag at cursor
lens section intro -p location.tavern
lens section --end         # close the current section (appends summary to parent)
lens section --end -l fast
```

A section creates a `[section:id]: #` annotation in the parent node and moves the cursor into the new child. `lens section --end` appends a summary and the closing tag, then moves the cursor back up.

- **Start:** `lens section <id>` — optional `-p` / `--pin`, `-u` / `--unpin` (repeatable). Add `+` to pin IDs to include linked objects, or `++` for full traversal.
- **End:** `lens section --end` — optional `-l` / `--llm` for the summary LLM.

## Collate (`lens collate`)

Carve a section out of already-written prose at an arbitrary node by specifying a line range:

```bash
lens collate intro /chapter-1 10 30
lens collate intro /chapter-1 10 30 -p place.tavern -l fast
```

Arguments: `ID ADDRESS START_LINE END_LINE`

- `ID` — key for the new child node (must not already exist).
- `ADDRESS` — narrative node address (e.g. `/chapter-1`, `my-story/chapter-1`).
- `START_LINE` / `END_LINE` — 1-based, inclusive line range to extract.

Options: `-p` / `--pin`, `-u` / `--unpin` (for summary context), `-l` / `--llm`.

The selected lines are moved into a new child node, an LLM summary is generated, and the range in the parent is replaced with the section annotation block. Any sub-nodes whose annotations fall entirely within the range are moved into the new section as its own children. The operation is one-shot and fully reversible with `lens rollback`.

The range may include complete annotation blocks, but cannot split one — selecting only the opening or closing tag of an annotation (or only part of its content) is an error.

## AI Operators

AI operators call the configured LLM and write the output into narrative nodes. All operators share these options:

| Option | Short | Purpose |
|--------|-------|---------|
| `--pin ID` | `-p` | Pin a KB object for this call (repeatable) |
| `--unpin ID` | `-u` | Suppress an inherited pin for this call (repeatable) |
| `--llm ID` | `-l` | Override the default LLM |
| `--retry` | `-r` | Discard current output and regenerate |

You can also pin KB objects inline by mentioning them as `@type.key` in your prompt — `lens write "describe @person.amy arriving at @place.market"` is equivalent to passing `-p person.amy -p place.market`. Only IDs that exist in the knowledge store are resolved; unknown mentions are ignored.

### `lens write`

Streams generated text into the cursor node, appending it inline.

```bash
lens write                          # continue writing (no instruction)
lens write "focus on the weather"   # write with a specific instruction
lens write --retry                  # discard and regenerate with the same config
lens write "new direction"          # discard and regenerate with updated instruction
lens write -p person.amy            # pin a knowledge object for this call
```

`write` records a `[write ... ]: #` annotation in the node file. Calling it again while that annotation is pending continues or retries the same transaction. Provide a new prompt or pins with `--retry` to update the configuration.

### `lens edit`

Proposes an LLM rewrite of a specific line range in a node, or performs a manual in-place replace, staging a claim annotation.

```bash
lens edit /chapter-1 10 20 "make it more tense"
lens edit /chapter-1 10 20 --retry            # regenerate with same instruction
lens edit /chapter-1 10 20 "shorter"          # regenerate with new instruction
lens edit /chapter-1 10 20 "fix it" -p place.inn
lens edit /chapter-1 10 20 "New text" --replace   # replace lines 10–20 directly (no LLM)
```

Arguments: `ADDRESS START_LINE END_LINE [PROMPT]`

- `ADDRESS` — narrative node address (e.g. `/chapter-1`, `my-story/chapter-1`).
- `START_LINE` / `END_LINE` — 1-based, inclusive line range to rewrite.
- `PROMPT` — editing instruction (LLM mode) or replacement text (`--replace` mode). Required for a fresh edit; optional on retry to reuse the previous instruction in LLM mode.

`edit` wraps the selected lines in a claim annotation (`[edit:eSTART_END]: #`) that is staged, then either streams the proposed replacement as an unstaged diff (LLM mode) or applies the provided replacement text directly (`--replace` mode). Use `lens rollback` to cancel, or `lens commit` to accept.

### `lens play`

Opens a play session sub-node for GM-voice narrative. Each call streams narrative into the session. Use `--end` to close the session.

```bash
lens play "I search the room"               # first call: auto-creates a play sub-node
lens play "I talk to the innkeeper"         # inside session: appends another block
lens play "engage the goblins" --module combat  # activate a rules module
lens play --retry                            # regenerate the last block
lens play --end                              # close the play session
lens play "I roll @roll d20+5" --wait       # append player line only; GM on a later play
```

Arguments: `[PROMPT]`

- `PROMPT` — what the player says or does. Required unless using `--end`.

Options:

- `--module` / `-m` — rules module key (a KB object under `rules.<key>`, e.g. `combat`, `downtime`). The module is pinned into the sub-node's front matter. Only one extra module is active at a time; switching removes the previous one. `rules.system` and `rules.rpg` are always auto-pinned.
- `--as` / `-as` — PC key to attribute the prompt to (e.g. `-as alice` → `[ALICE]`); must be a pinned `pc.*`.
- `--retry` — discard the last block and regenerate it.
- `--end` — close the play session and return to the parent node.
- `--wait` — append the attributed player line only (no LLM). Resolvable `@type.key` mentions are expanded into an HTML comment so the next normal `play` still sees that KB text without cluttering rendered markdown.

**Flow:** The first call outside a play sub-node auto-generates an ID (e.g. `play-combat-engage-the-goblins`) and creates the sub-node, auto-pinning `rules.system` and `rules.rpg`. Subsequent calls detect that the cursor is already inside a play sub-node and append new inline blocks. Module and pin changes update the front matter in place.

Requires the `rpg` dataset, at least one pinned `pc.*` object (at any ancestor level), and is dataset-gated. Use `lens section` within a play session to nest scope (e.g. a focused combat), then start another `play` call after.

### `lens design`

Opens a KB design workspace. Each call streams an inline response block into a design sub-node. When you are done, `--end` extracts all `kb` blocks from the sub-node into the knowledge store.

```bash
lens design "design a tavern"               # first call: auto-creates a sub-node
lens design "add a secret basement"         # inside design node: appends another block
lens design --module encounter "the ambush" # pin a design module for this session
lens design --retry                         # regenerate the last block
lens design --end                           # extract KB objects and close the session
```

Arguments: `[PROMPT]`

- `PROMPT` — design task. Omit to let the module guide the session.

Options:

- `--module` / `-m` — design module key (a KB object under `design.<key>`, e.g. `encounter`). The module is pinned into the sub-node's front matter so it appears in every subsequent call's context. Only one module is active at a time; switching removes the previous one.
- `--retry` — discard the last inline block and regenerate it.
- `--end` — close the design session: runs `kb extract` on the full sub-node content, writes inserted/updated KB objects, and appends the closing tag to the parent node.

**Flow:** Both `design` and `play` share the same session pattern (see `SessionOperator`). The first call outside a design sub-node auto-generates an ID (e.g. `design-encounter-the-ambush`) and creates the sub-node with its front matter. Subsequent calls detect that the cursor is already inside a design sub-node and append a new inline block instead of creating another sub-node. Module and pin changes on subsequent calls update the front matter in place.

After `--end` completes, newly inserted and updated KB objects are printed. Use `lens rollback` to undo both the narrative annotation and any KB changes.

### `lens rollback`

Discards the pending operator transaction. The behaviour differs by operator type:

- **Inline operators** (`write`): unstaged changes are discarded (`git checkout -- .`).
- **Mutation operators** (`edit`): a *compensating transaction* is applied — the staged claim tags are removed and the original text is restored, leaving no trace of the operator in the history.

```bash
lens rollback
```

## Media attachments (`lens attach`)

Attach a local media file at the narrative cursor. The file must live inside the project's configured `mount_point` directory (see below). The server proxies these files so the web UI can display them.

```bash
lens attach hero.jpg                 # embed image at cursor
lens attach sub/clip.mp4             # embed video from a subdirectory
lens attach docs/brief.pdf           # embed document link
lens attach hero.jpg --preview       # validate only — print type without writing
```

Arguments: `PATH`

- `PATH` — path relative to `mount_point`. Subdirectories are allowed (e.g. `photos/hero.jpg`).

Options: `--preview` — validate the file exists and report its type without inserting anything.

Supported file types:

| Type     | Extensions                          | Embed format        |
|----------|-------------------------------------|---------------------|
| image    | `.jpg` `.jpeg` `.png` `.webp` `.gif` | `![name](url)`      |
| video    | `.mp4` `.webm` `.mov` `.avi`        | `<video>` tag       |
| document | `.pdf` `.txt` `.md`                 | `[name](url)` link  |

The command is only available when `mount_point` is set in `lens.toml`. If the project has no mount point, `lens attach` does not appear.

### Configuring `mount_point`

Add `mount_point` to the `[project]` section of your `lens.toml`:

```toml
[project]
narrative   = "my-campaign"
mount_point = "media"          # relative to the project root, or an absolute path
```

The `media/` directory (or whatever path you choose) is the root for all attached files. It is not managed by Lens — create and organise it however you like. Only files inside this directory can be attached.

A relative path is resolved from the project root. An absolute path is used as-is.

