# CLI reference

Full reference for Lens commands, the knowledge store, pins, sections, and AI operators. Project configuration (`lens.toml`, backends, mounts): **[docs/configuration.md](../../docs/configuration.md)**.

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
   lens explain    # what is in the prompt at the cursor: size and provenance per component
   lens check      # verify lens.toml, API keys, mount, and paths (--skip-network optional)
   lens kb         # knowledge store (see lens kb --help)
   lens section    # start or end a section at cursor
   lens collate    # crete a section after the fact from completed prose
   lens compress   # AI: collate a range at the cursor from a natural-language prompt
   lens pin        # kb / var / param at nodes (see lens pin --help)
   lens write      # AI: generate narrative text at the cursor
   lens edit       # AI or manual: rewrite/replace a selected line range in narrative
   lens chat       # AI: in-character speech (--as / optional --with session)
   lens rewind     # move the cursor back to a node or line, deleting what comes after
   lens rollback   # discard or compensate a pending operator transaction
   lens commit     # stage all changes (git add -A)
   lens checkpoint # stage, commit, and push; optional message and --no-push
   lens refresh    # fetch and fast-forward from remote; --reset to match remote exactly
   lens media      # attach files or generate images (`lens media --help`)
   ```

Dataset-gated commands (from dataset extensions, e.g. `lens dnd` when `lens-dnd` is listed) and operators (`play`, `advance` when `rpg` is listed) appear only when the dataset is in `[project] datasets` and resolves. See [RPG](../rpg/README.md) and [datasets/README.md](../../datasets/README.md#dataset-extensions-optional-python).

## Project commands

### `lens init`

Initialize a Lens project in the current git repo. Creates `lens.toml` (with a comment pointing to `lens use`), `knowledge/`, and `narrative/`. Does not set the active narrative or add LLM configuration. Requires an existing git repository.

### `lens use <slug>`

Select the active narrative in `lens.toml`. *slug* must be alphanumeric with optional underscores and hyphens. Creates the narrative folder and root `_node.md` if they do not exist.

For the **companion** dataset, bootstrap a companion chat narrative (KB stubs from templates, pins, chat params):

```bash
lens use my-chat --companion companion.mara --human human.adam
```

Requires `datasets = ["companion"]` in `lens.toml`. See [datasets/companion/README.md](../../datasets/companion/README.md).

### `lens check`

Validate configuration and environment for the current project: each `[[llm]]` entry’s `base_url` is probed over TCP (unless `--skip-network`), `api_key_env` variables are present when set, optional `mount_point` is checked (local directory exists, or S3 URI with required `AWS_*` variables), bundled `datasets` entries exist, `prompt_pack` file is present when set, and the configured `narrative` folder exists when set. Exits with status 1 if any **error**-level check fails; **warn**-level issues are printed but do not fail the command.

- `--skip-network` — Skip LLM host/port reachability; still validates URL shape, keys, and paths.

### `lens stats`

Count knowledge objects by type and list narrative trees with node counts. Shows the active narrative cursor and whether an open transaction exists (and its owner).

- `-v` / `--verbose` — Print pending transaction diff (unstaged) and staged (checkpoint) diff.

### `lens explain`

Assemble the prompt for a cursor exactly as the operator would, then report it instead of sending it. Read-only: nothing is written, no transaction is opened, and no model is called — it works with no LLM configured.

```bash
lens explain                        # the current cursor, operator detected from the tree
lens explain /chapter-1             # a different node
lens explain /chapter-1 42          # as of line 42 of that node
lens explain --operator play        # assemble as play (auto-pins and modalities differ)
lens explain --sort size            # biggest components first, within each block
lens explain --json                 # the full report, for tooling
```

Arguments: `[ADDRESS] [LINE]`

- `ADDRESS` — node to report on (e.g. `/chapter-1`, `/@cursor`). Defaults to the cursor.
- `LINE` — optional 1-based line; the current passage is reported as ending there.

**A leading `/` means the active narrative**, and every segment after it is a node key; a bare first segment names the narrative instead. With `Act-1` active and a `Walstein` node inside it:

| Address | Resolves to |
|---|---|
| `/` | root of the active narrative (`Act-1`) |
| `/Walstein` | `Walstein` inside the active narrative |
| `Act-1/Walstein` | the same node, spelled explicitly |
| `Design` | root of the `Design` narrative |
| `/Act-1/Walstein` | ✗ a node named `Act-1` *inside* `Act-1` — does not exist |

The last row is the common slip. When an address does not resolve, Lens suggests one that does (verified against disk) or lists the node keys that exist at the nearest ancestor. A trailing slash — what shell tab-completion gives you — is accepted.

Options:

- `-o` / `--operator <name>` — assemble as this operator instead of the one detected at the cursor. Auto-pins, required modalities, system prompt, and instruction all differ per operator, so the report does too.
- `-p` / `--prompt <text>` — include a prompt, as if passed to the operator.
- `-s` / `--sort order|size|id` — order components within each block (default `order`).
- `--json` — emit the full report instead of the table.
- `-v` / `--verbose` — show block-framing and message-separator rows so the columns visibly add up, list components that never reach the model (warnings, participants), and print the cache-position note.
- `--chars-per-token <n>` — divisor for the token estimate (default 4).

Each row reports the component id (`kb:pc.alice`, `rules-companion:rules.encounter`, `mention:spell.aid`, `narrative:/chapter-1:narrative_summary`, `render-system`, `render-task`), the block it lands in, its bytes and estimated tokens with a share of the total, and **why it is there**:

| Provenance | Meaning |
|---|---|
| `node_pin` | `kb_pin` on a named ancestor node |
| `expansion` | pulled in by a `+` suffix on another pin |
| `mention` | an `@` mention in the narrative or prompt |
| `rules_companion` | `rules.<type>` auto-added for pinned objects of that type |
| `module` | the active session module (or its template) |
| `modality` | pinned by an active modality |
| `operator_pin` / `operator` | the operator's own pins, system prompt, or instruction |
| `narrative` | ancestor summaries, the current passage, or parsed conversation turns |

Totals are reported per block and overall, so "my next call costs about 33k tokens" and "43% of my knowledge block is always-on rules text" are one command away.

Every level reconciles: a block equals its components plus its framing (the `--- begin/end <title> ---` wrapper and separators), and the total equals the blocks plus the message separators — in both bytes and tokens. The framing and separator rows are hidden by default because they are the same handful of bytes on every run; `-v` shows them.

Token counts are an estimate (characters divided by a fixed divisor) because tokenization is model-dependent and Lens ships no tokenizer; byte counts are exact. Each part is estimated on its own and aggregates are sums of their parts, so the grand total runs a few tokens above a single estimate of the whole prompt. The `cache` column is currently a heuristic (stable blocks vs per-call blocks) and will report measured prefix-cache boundaries once prompt caching lands.

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

If the template's own front matter declares a `tags:` key, those tags are applied to the new object on creation (once — not re-asserted later, and not copied verbatim into the new object's body). See [Template default tags](../../docs/configuration.md#template-default-tags) in the configuration docs.

You can create links to KB items by using the relative `/kb` address, e.g. `[Bandit](kb/stat.bandit)`. This opens to a new KB page in the UI. If a KB document with the link has a front matter entry for `kb-details: true`, the links will be opened in a detail panel _under_ the main content instead.

KB items can also include interactive inline controls if rendered in the UI in preview mode; these are triggered by the following conventions in the raw markdown source:

| Markdown | Rendered as |
|----------|-------------|
| `` `[ ]` `[x]` `` | Unchecked or checked checkbox |
| `` `#5` `` | Number input (0–∞) |
| `` `#3/10` `` | Number input (0–max, clamped) |
| ` ```notes` … ` ``` ` | Auto-growing `<textarea>` |


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

Edit or create a knowledge object using AI. Uses the same mutation pattern as `lens edit`: a fresh call wraps the KB file in staged claim tags (`[kb_edit:ke]: #` / `[/kb_edit:ke]: #`), runs the LLM, and proposes the replacement as an unstaged diff. `lens rollback` removes the claim tags and restores the original; `lens commit` / `lens checkpoint` accepts the proposed changes.

Works on existing objects (including dataset items — copy-on-write applies) or creates new ones from scratch. When creating a new object, the type template is included in the prompt by default (unless `--include-template` is omitted).

```bash
lens kb edit person.hero "add a dark secret"
lens kb edit person.hero "make them more mysterious" -p place.castle
lens kb edit person.new-npc "describe a weary traveler" -t
lens kb edit person.hero "revise backstory" -c "/chapter-1 10 30"
lens kb edit person.hero "tighten description" --reasoning medium
```

Arguments: `ID INSTRUCTION`

- `ID` — object ID (e.g. `person.hero`). Creates the object if it does not exist.
- `INSTRUCTION` — AI instructions for what to write or change.

Options:

| Option | Short | Purpose |
|--------|-------|---------|
| `--pin ID` | `-p` | Pin a KB object for this call (repeatable) |
| `--unpin ID` | `-u` | Suppress an inherited pin (repeatable) |
| `--context ADDRESS [START [END]]` | `-c` | Narrative context: just an address (e.g. `/chapter-1`) for full crawl with ancestor pin resolution; with line bounds (e.g. `/chapter-1 10` or `/chapter-1 10 30`) injects as a `REF[…]` slice with no ancestor pins. Not available in dataset mode. |
| `--include-template` | `-t` | Include the type template (`_template.md`) in the LLM prompt. Enabled by default when creating a new object. |
| `--llm ID` | `-l` | Override the default LLM |
| `--reasoning LEVEL` | — | Reasoning override: `none`, `low`, `medium`, `high` |
| `--retry` | `-r` | Discard the current claim, rollback, and re-propose. The original content is extracted from between the claim tags and the LLM regenerates. |

**Mutation flow:**

1. **Fresh call:** If the object exists, its current content is read. The file is written wrapped in `[kb_edit:ke]: #` (open tag) and `[/kb_edit:ke]: #` (close tag) with the original content between them. This is staged (`git add`).
2. **LLM generates** new content based on the instruction, pinned KB objects, template, and context (full narrative crawl or `--context` slice refs).
3. **Propose:** The claim block is replaced with just the new content, written as an unstaged diff — the staged claim tags remain as a record.
4. **Rollback:** `lens rollback` stages the claim tags (restoring the original content) then unstages them, leaving the file unchanged.
5. **Commit:** `lens commit` / `lens checkpoint` stages the unstaged diff, committing both the tags (now in git history) and the new content.

**Retry:** `lens kb edit ... --retry` detects the pending `[kb_edit:ke]` annotation, rolls back to the original claim-wrapped state, re-extracts the original content, and re-runs the LLM with the same (or updated) parameters. The new proposal replaces the old one.

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

# A type is a tag — no tagging required:
lens kb with-tag design                          # Every design.* module, with what each is for
lens kb with-tag rules                           # Every rules.* object

# OR groups: use (a b c) for tags that match any of a, b, or c. Quote for shell:
lens kb with-tag "(cr:1-2 cr:1-4)" "(type:undead type:humanoid)" size:large
```

- Base form prints object IDs with their tags, then each object's **first three lines** indented beneath — by convention its name and what it is for, so a wide search is readable without expanding it:

  ```
  stat.ghoul  [cr:1 type:undead]
      **Ghoul** · Medium Undead, Chaotic Evil
      **AC** 12 · **HP** 22 · **Speed** 30 ft.
  ```

  See [first three lines](../../docs/configuration.md#first-three-lines). `-e/--expand` prints whole bodies instead, where the headline is already the top of each one.
- **A bare object type is a valid tag**: `with-tag design` matches every `design.*` object whether or not it carries tags. Types also show up in `lens kb list-tags`.
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

When Lens looks up a KB object it searches the project first, then each dataset in the order listed (last wins for conflicts). This means you can `lens kb get`, `lens pin kb add`, or reference any dataset object exactly as if it were a project-local object — no explicit import step required.

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
| `rpg` | RPG play operators (`play`, `advance`); see [RPG](../rpg/README.md). |

External datasets (e.g. private `lens-dnd` with `lens dnd` / `balance_encounter`) are documented in [datasets/README.md](../../datasets/README.md).

## Prompt store (`lens prompt`)

Operator and shared prompt text is resolved with copy-on-write precedence:

1. built-in Lens prompts (`lens/prompts/default.toml`)
2. optional selected prompt pack (`[project] prompt_pack = "<name>"`)
3. project-local overrides (`prompts/prompts.toml`) — always wins

Editing an inherited prompt via `lens prompt set` creates/updates the project-local
override. Built-in and pack files are never modified by project commands.

| Command | Purpose |
|---|---|
| `list` | List prompt keys (optionally by operator/group) |
| `get` | Print effective prompt text and source layer |
| `set` | Set/update project-local override for a key |
| `clear` | Remove project-local override for a key |
| `path` | Print the project override file path (`--builtin` for default file) |
| `packs` | List available prompt packs (`*` marks selected pack) |
| `use-pack` | Select a single prompt pack in `lens.toml` |
| `clear-pack` | Clear selected prompt pack |

Examples:

```bash
lens prompt list --operator write
lens prompt get write.system
lens prompt set write.system "You are concise and vivid."
lens prompt clear write.system
lens prompt packs
lens prompt use-pack it
```

## Pins (`lens pin`)

Subcommands: **`kb`** (knowledge in prompts), **`var`** (narrative `vars` for `@var:`), **`param`** (operator defaults under `params`). Run `lens pin --help`.

### Knowledge (`lens pin kb`)

Pins attach knowledge objects to a node's front matter so they are automatically included in AI operator prompts. Unpins cancel pins inherited from ancestor nodes.

| Command    | Purpose                                         |
|------------|-------------------------------------------------|
| `add`      | Add to `kb_pin` (include in prompts)            |
| `remove`   | Remove from `kb_pin`                            |
| `block`    | Add to `kb_unpin` (cancel an ancestor pin)      |
| `unblock`  | Remove from `kb_unpin`                          |
| `mention`  | In context **from this point**, for one AI turn |
| `include`  | In context **from this point**, rest of the node|

All `kb` commands take one positional ID and an optional positional node address (default: cursor). Use `-i`/`--id` (repeatable) for multiple IDs, and `--node`/`-n` when combining with `-i`.

```bash
lens pin kb add person.amy                            # pin at cursor
lens pin kb add person.amy /amy-story                 # pin at specific node
lens pin kb add person.amy test-narrative/amy-story   # full address
lens pin kb add -i person.amy -i place.city --node /amy-story  # multiple IDs

lens pin kb block person.amy /amy-story   # suppress an ancestor pin here
lens pin kb remove person.amy             # undo a pin
lens pin kb unblock person.amy            # undo a block

lens pin kb mention spell.aid             # one AI turn, from here on
lens pin kb include rules.grappling       # rest of this node, from here on
lens pin kb mention spell.aid /chapter-1  # only applies once the cursor is there
```

Node addresses follow the format `[<narrative>/]<key>[/<key>...]` or `/@cursor`. Run `lens pin kb <command> --help` for details.

#### Mentions and includes are a different scope

`add` / `remove` / `block` / `unblock` edit front matter: they apply to the whole node and are inherited by children. `mention` and `include` instead append an annotation at the node's tail, and the object is rendered **there** — inside the passage, at the point you asked for it — rather than in `[RELEVANT KNOWLEDGE]`. They are never inherited — not by sub-nodes, and not upward from an ancestor.

A **mention** stops expanding after one AI turn; an **include** lasts for the rest of the node. Nothing counts down and nothing is deleted: expiry is computed from how far the annotation is from the cursor, so retrying does not consume a mention and rewinding past an expiry brings it back. To refresh an expired mention, mention it again.

They take effect **only in the node they were written into, and only while that node is the cursor**. That is the opposite of `add`, where targeting an ancestor is the whole point because pins inherit downward. Passing a node address is therefore only useful to pre-stage a node you are about to move into, and the command says so when the target is not the cursor.

The same thing is available per invocation as `--mention` / `--include` on `write`, `play`, `chat`, and `design` — repeatable, and combinable with `--pin`. Writing `@type.key` in a prompt is the shortcut for `--mention`: each distinct object named gets one annotation, in the order they appear.

```bash
lens play "I cast @spell.aid on @pc.rowan"          # two one-turn mentions
lens write "Describe the fight" --include rules.combat --pin loc.arena
```

### Vars (`lens pin var`)

Set or unset `vars` in node front matter. Default target is the cursor; use `--node` / `-n` for another address. Value tokens are joined with spaces (quote phrases as needed).

```bash
lens pin var set mood "ominous and quiet"
lens pin var unset mood
lens pin var set color blue --node /chapter-1
```

### Operator params (`lens pin param`)

Set or unset keys under `params.global` or `params.<operator>` (e.g. `write`, `chat`). The first positional after `set` / `unset` is the scope (`global` or a slug). Values are coerced like YAML literals where obvious (`true` / `false`, integers, floats); otherwise stored as strings. Use `--node` / `-n` to target a node other than the cursor.

```bash
lens pin param set global llm_id fast
lens pin param set write reasoning true
lens pin param unset write reasoning
lens pin param set global temperature 0.9 --node /chapter-1
```

## Sections (`lens section`)

Sections structure the narrative tree by creating child nodes under the cursor.

```bash
lens section intro          # create child node "intro" and open section tag at cursor
lens section intro -p location.tavern
lens section --end         # close the current section (appends summary to parent)
lens section --end -l fast
lens section --end "call out the clue on the napkin"   # optional text: extra instructions for the summary LLM
```

A section creates a `[section:id]: #` annotation in the parent node and moves the cursor into the new child. `lens section --end` appends a summary and the closing tag, then moves the cursor back up.

- **Start:** `lens section <id>` — optional `-p` / `--pin`, `-u` / `--unpin` (repeatable). Add `+` to pin IDs to include linked objects, or `++` for full traversal.
- **End:** `lens section --end` — optional `-l` / `--llm` for the summary LLM. With `--end`, the optional positional argument (same slot as `<id>` when starting) is **not** a section id; it is optional free-text guidance merged into the summary request.

## Collate (`lens collate`)

Carve a section out of already-written prose at an arbitrary node by specifying a line range:

```bash
lens collate intro /chapter-1 10 30
lens collate intro /chapter-1 10 30 -p place.tavern -l fast
lens collate intro /chapter-1 10 30 --summary-guide "emphasize the foreshadowing in dialogue"
```

Arguments: `ID ADDRESS START_LINE END_LINE`

- `ID` — key for the new child node (must not already exist).
- `ADDRESS` — narrative node address (e.g. `/chapter-1`, `my-story/chapter-1`).
- `START_LINE` / `END_LINE` — 1-based, inclusive line range to extract.

Options: `-p` / `--pin`, `-u` / `--unpin` (for summary context), `-l` / `--llm`, `--summary-guide` / `-g` (optional extra instructions for the collate summary LLM).

The selected lines are moved into a new child node, an LLM summary is generated, and the range in the parent is replaced with the section annotation block. Any sub-nodes whose annotations fall entirely within the range are moved into the new section as its own children. The operation is one-shot and fully reversible with `lens rollback`.

The range may include complete annotation blocks, but cannot split one — selecting only the opening or closing tag of an annotation (or only part of its content) is an error.

If any **pinned** KB object in the collate summary crawl carries a `remember.*` tag, the same **Remember** pass described under `lens chat` may run after the summary (see pins on that command).

## Compress (`lens compress`)

The LLM reads the **target** node (the narrative **cursor** by default, or the node given with `--node` / `-n`, same addressing rules as `lens pin kb`), decides whether your description matches a contiguous range, and either calls an internal `compress_collate` tool (verbatim line anchors on the AI-visible body, same idea as `kb_patch`) or answers in plain text without collating. On success it runs the same structural work as `lens collate` at that node’s address (summary, optional Remember pass with pins — see **Collate** above).

```bash
lens compress "the dinner conversation before they leave"
lens compress "opening skirmish" -p place.cave -l fast
lens compress "aside with the merchant" --summary-guide "keep the joke about the scales"
lens compress "tighten this beat" --node /chapter-3/scene-two
```

Arguments: a single **PROMPT** string (required) — what to pull into its own child section.

Options: `-n` / `--node` (narrative address; default cursor), `-p` / `--pin`, `-u` / `--unpin`, `-l` / `--llm`, `--reasoning`, `--summary-guide` / `-g` (passed through to the collate summary step when a range is chosen).

If the model does not call the tool, the CLI prints its explanation (e.g. nothing matched or the span would split a section summary block). Use `lens collate` with explicit line numbers when you need full control.

## AI Operators

AI operators call the configured LLM and write the output into narrative nodes. All operators share these options:

| Option | Short | Purpose |
|--------|-------|---------|
| `--pin ID` | `-p` | Pin a KB object for this call (repeatable) |
| `--unpin ID` | `-u` | Suppress an inherited pin for this call (repeatable) |
| `--llm ID` | `-l` | Override the default LLM |
| `--retry` | `-r` | Discard current output and regenerate |
| `--reasoning` | - | `none`,`low`,`medium`,`high` overrides reasoning amount |

You can also pin KB objects inline by mentioning them as `@type.key` in your prompt — `lens write "describe @person.amy arriving at @place.market"` is equivalent to passing `-p person.amy -p place.market`. Only IDs that exist in the knowledge store are resolved; unknown mentions are ignored.

### Prompt syntax

Prompts for AI operators (`write`, `play`, `edit`, `chat`, `design`, `lens media generate`, etc.) support inline modifiers. These are resolved **before** the LLM (or image API) sees the text.

#### `@` mentions

| Form | Effect |
|------|--------|
| `@type.key` | Pin a KB object for this call (same as `--pin type.key`) |
| `@/path@start:end` or `@narrative/path@start:end` | Quote a line slice from a narrative node into context (`REF['…']` block) |
| `@var:key` | Substitute a string from inherited node `vars` (front matter; see `lens pin var`) |
| `@now` | Current timestamp (project `locale`) |

In the web UI prompt field, node slices can be entered as `@/path start end` or `@narrative/path start end`; the client normalizes them to `@path@start:end` before calling the API.

#### Dice (`@roll`)

Inline dice expressions are evaluated locally ([python-dice](https://github.com/borntyping/python-dice)); the model only sees the rolled result.

| Form | Example |
|------|---------|
| `@roll <expr>` | `@roll d20+5` (no spaces in the expression) |
| `@roll (<expr>)` | `@roll (2d6 + 3)` (spaces allowed inside parentheses) |

A space after `roll` is required. Notation includes `d20`, `2d6`, `4d6h3`, `2d20h1` (advantage), and arithmetic.

```
lens play "I try to sneak past the guard — @roll d20+3 stealth check"
```

Invalid expressions abort the command with an error; the narrative is never written with an unresolved roll.

For tabletop pacing: **`lens play`** with a prompt appends only the player line; use **`lens play --pass`** when you want the GM response in the same invocation. See [RPG / play](../rpg/README.md).

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

### `lens chat`

Streams dialogue as a specific knowledge-base character (`--as` / `-as`). The model receives that object’s text in the task (it is not added as a pin, so it does not duplicate “relevant knowledge”). Requires an active narrative (`lens use`).

**Character framing:** `--as` picks the KB character whose sheet is inlined into the task, together with the  chat system prompt (in-character voice and boundaries). After the session is open, when `--as` / `--with` match the pair recorded in the session’s parent annotation, your `PROMPT` is appended as your character’s line and the bundled instructions bias narration toward **first** person and **second** person toward that counterpart (`chat.with_line_instruction`). Change `--as` or `--with` and the same text is read as **third-person** stage direction for a one-off beat (e.g. a waiter interrupting a date), not as the other character speaking.

**One-shot (no `--with`):** With `--as <kb.id>` and optional stage directions, the AI speaks once in the **current** node (inline), like a single in-character beat (descriptions in third person).

**Session (`--with`):** With `--as` and `--with` / `-w` (the KB id of the character **you** play), Lens creates a **chat** sub-node under the cursor. Your prompt is treated as stage directions for the opening exchange. Inside that session, later invocations can omit `--with`; plain text is appended as your character’s line (blockquote), then the AI responds as `--as`. You can pass a new `--as` on a later call to switch which character the AI voices for a one-off beat.

The `--with` id is merged into crawl context the same way as `--as` (not written to `kb_pin` unless you add it with `-p`).

**Remember (durable KB updates when prose is summarized):** When Lens summarizes a block of prose, it can run a short **remember** pass that may call `kb_patch` on specific KB objects you designate.

What you do:

1. **Mark patch targets** — On any KB object you want the remember step to be allowed to edit, add a dot-tag `remember.<name>` (for example `remember.core-memories` on `lore.alice`). Only objects that are **pinned** into the crawl at summarize time count (same pin rules as elsewhere).

2. **Provide optional instructions** — Create a KB object whose id is exactly that tag, e.g. `remember.core-memories`, with the guidance the remember model should follow. If you are trying to update a specific/structured object, stay `remember.<type>` and the system will also give the AI its template.For example to update `location.home` tag it with `remember.location` and the template will be used, plus you can actually create `remember.location` to specific when and what to remember inside a location.

3. **Trigger** — The remember step runs when Lens summarizes session content on close (**`lens chat --end`**, **`lens play --end`**) or when you summarize a section using **`lens section --end`** or  **`lens collate`**. It reads the passage that is about to be compressed, not the whole node. If nothing needs changing, the model leaves objects alone. (operators that use `kb extract` like `design` and `advance` does not use this path since they already manipulate KB items another way)

Only ids that carry a `remember.*` tag are patch targets; `kb_patch` is restricted to that set for that call.

```bash
lens chat --as npc.innkeeper "warn them about the curfew"
lens chat --as npc.bob --with pc.amy "Amy corners Bob behind the stables"
lens chat "I never saw the letter."              # inside session: your line, then AI as --as
lens chat --as npc.guard "freeze!"               # mid-session: switch AI voice to the guard
lens chat --retry                                # discard last generation and regenerate
lens chat --end                                  # close session with a short prose summary
lens chat --as npc.bob --with pc.amy -s alley "opening beat"   # optional sub-node id (--slug / -s)
```

Arguments: `[PROMPT]`

- `PROMPT` — Stage directions for a new or guided exchange (especially with `--with`), your character’s line inside an open session, or the beat for a one-shot. Can be omitted when using only `--end` or `--retry` (see `lens chat --help`).

Options:

- `--as` / `-as` — KB id the AI embodies (e.g. `npc.bob`, `pc.alice`). Required for new inline or session calls; inside an open session it can override the voiced character.
- `--with` / `-w` — KB id of your character; starts (or re-enters explicit) session mode when set together with session handling. After the session exists, you may omit it and Lens continues the active chat session.
- `--slug` / `-s` — Sub-node key for a **new** session (default: auto-generated from characters and prompt). If you pass a bare name, Lens prefixes it with `chat-` when needed. Not used with `--end` or `--retry`.
- `-p` / `--pin`, `-u` / `--unpin`, `-l` / `--llm`, `--reasoning`, `-r` / `--retry` — same ideas as other AI operators.
- With `--end`, an optional `PROMPT` is treated as extra instructions for the session summary LLM (same narrative templates as usual, plus your guidance).

**Flow:** Opening a session writes an unclosed ``[`chat:<id>`]: #`` annotation on the parent and creates the child in one pending transaction (rollback drops the whole session). Inside the child, your lines are stored as Markdown blockquotes with a ``[Name]`` speaker tag (derived from the KB id). One-shot inline uses the chat operator without a sub-node. This command is not dataset-gated.

### `lens play`

Opens a play session sub-node for GM-voice narrative. Each call streams narrative into the session. Use `--end` to close the session.

```bash
lens play "I search the room"               # first call: auto-creates a play sub-node
lens play "I talk to the innkeeper"         # inside session: appends another block
lens play "engage the goblins" --module combat  # activate a rules module
lens play --retry                            # regenerate the last block
lens play --end                              # close the play session
lens play "I roll @roll d20+5"              # append player line only; GM on a later play
lens play --pass                            # GM responds (no new player line)
lens play "I attack" --pass                 # append player line, then GM responds
```

Arguments: `[PROMPT]`

- `PROMPT` — what the player says or does. Required unless using `--end`, `--retry`, or `--pass`. With `--end` only, an optional `PROMPT` is extra instructions for the play-session summary LLM.

Options:

- `--module` / `-m` — rules module key (a KB object under `rules.<key>`, e.g. `combat`, `downtime`). The module is recorded on the session's open annotation. **Repeatable**, and passing it again *replaces* the active set rather than appending. `rules.system` and `rules.rpg` are always auto-pinned.
- `--as` / `-as` — PC key to attribute the prompt to (e.g. `-as alice` → `[ALICE]`); must be a pinned `pc.*`.
- `--retry` — discard the last block and regenerate it.
- `--end` — close the play session and return to the parent node.
- `--pass` — call the GM / LLM to respond. With no `PROMPT`, it generates a GM response based on the current passage. With a `PROMPT`, it first appends the player line, then generates the GM response.

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

- `--module` / `-m` — design module key (a KB object under `design.<key>`, e.g. `encounter`). The module is recorded on the session's open annotation so it resolves into every subsequent call's context, along with its `+` links and its `<key>._template`. **Repeatable:** `--module encounter --module tracker` runs one session against both. Passing `--module` again on a later call *replaces* the active set rather than appending, so the flag always means "these are the modules now"; keys are validated before anything is written.
- `--retry` — discard the last inline block and regenerate it.
- `--end` — close the design session: runs `kb extract` on the full sub-node content, writes inserted/updated KB objects, and appends the closing tag to the parent node.

**Flow:** Both `design` and `play` share the same session pattern (see `SessionOperator`). The first call outside a design sub-node auto-generates an ID (e.g. `design-encounter-the-ambush`) and creates the sub-node with its front matter. Subsequent calls detect that the cursor is already inside a design sub-node and append a new inline block instead of creating another sub-node. Module and pin changes on subsequent calls update the front matter in place.

After `--end` completes, newly inserted and updated KB objects are printed. Use `lens rollback` to undo both the narrative annotation and any KB changes.

### `lens rollback`

Discards the pending operator transaction. The behaviour differs by operator type:

- **Inline operators** (`write`): unstaged changes are discarded (`git checkout -- .`).
- **Mutation operators** (`edit`, `kb edit`): a *compensating transaction* is applied — the staged claim tags are removed and the original text is restored, leaving no trace of the operator in the history.

```bash
lens rollback
```

## Media (`lens media`)

The `lens media` group is only registered when `mount_point` is set in `lens.toml`.

### `lens media attach`

Attach a media file at the narrative cursor. The file must live inside the project's configured `mount_point` directory (see below). The server proxies these files so the web UI can display them.

```bash
lens media attach hero.jpg                 # embed image at cursor
lens media attach sub/clip.mp4             # embed video from a subdirectory
lens media attach docs/brief.pdf           # embed document link
lens media attach hero.jpg --preview       # validate only — print type without writing
lens media attach bg.jpg --fg amy.png      # embed a background+foreground composite (see below)
```

Arguments: `PATH`

- `PATH` — path relative to `mount_point`. Subdirectories are allowed (e.g. `photos/hero.jpg`).

Options:

- `--preview` — validate the file exists and report its type without inserting anything.
- `--fg PATH` — path (relative to `mount_point`) of a foreground image to layer over `PATH` (the background), creating a composite attachment. Both files must be images; not compatible with `--preview`.

Supported file types:

| Type     | Extensions                          | Embed format        |
|----------|-------------------------------------|---------------------|
| image    | `.jpg` `.jpeg` `.png` `.webp` `.gif` | `![name](url)`      |
| video    | `.mp4` `.webm` `.mov` `.avi`        | `<video>` tag       |
| document | `.pdf` `.txt` `.md`                 | `[name](url)` link  |

**Compositing (Visual Novel mode):** tag a media file's sidecar metadata with a top-level `composite: background` or `composite: foreground` key (see the web UI's media metadata panel, or `lens media` metadata routes) to mark it as one layer of a scene. `lens media attach BG --fg FG` embeds both as a single composite attachment (`<div class="lens-vn-composite">…</div>`, containing both images) — VN playback renders the background full-bleed with the foreground centered on top; plain reading mode renders the same pair stacked via CSS. In the web UI, attaching a composite-tagged image from the media carousel prompts you to pick its complementary layer before attaching. CLI direct selection (as above) never prompts — pass `--fg` explicitly or it attaches a single plain file.

### `lens media generate`

Generate images with the configured **`[[image]]`** backend (see your `lens.toml`) and save results under `generated/<slug>/` on the mount.

```bash
lens media generate "a moonlit cliff, oil painting"
lens media generate "portrait" --model flux-pro --aspect 16:9 --size 1k --batch 2 --slug portraits
lens media generate --from generated/my-run/b_1.yaml    # replay params from a batch sidecar; CLI flags override
```

**Positional:** `PROMPT` — required unless `--from` supplies a sidecar with a stored prompt. May include `@` KB mentions like other commands.

**Common options:** `--model` / `-m`, `--aspect` / `-a`, `--size` / `-s`, `--batch` / `-b`, `--slug`, `--negative` / `-n`, `--from` — batch sidecar YAML under the mount (mount-relative or absolute path inside `mount_point`).

**Reference images (`--ref`):** Repeatable. Each value is a **mount-relative** path to an image that already exists on the mount (e.g. a previous output like `generated/my-slug/b_1_r_1.png`). Those files are sent to the image provider as **input** where supported.

- **S3-only:** Reference images work only when `mount_point` is an **`s3://...`** URI (S3-compatible object storage). Lens creates **short-lived presigned HTTPS URLs** so the provider can `GET` the bytes directly from storage. A **local directory** mount cannot be used for `--ref` (there is no URL the provider can fetch).
- **Backend:** Reference images are allowed only when the resolved `[[image]]` API declares support (see `API_CAPABILITIES` on that implementation, e.g. A2E sets `supports_reference_images`). Other APIs omit the feature until implemented.

In the web UI, `--ref` is offered when stats report a cloud mount and `reference_images_supported` (at least one configured backend accepts reference images).

### `lens media tts`

Synthesize speech with the configured **`[[speech]]`** backend for a **narrative node**. Eligible lines become chunks; audio is stored under **`tts-cache/`** on the configured **`mount_point`** (local or S3) and reused when the text for a chunk is unchanged.

```bash
lens media tts /@cursor
lens media tts /chapter-1 --model alt --voice ara --language en
lens media tts /scene-3@12
lens media tts campaign/act-1@5:40
```

**Positional:** `ADDRESS` — narrative node address (required). Append **`@line`** or **`@start:end`** for a physical line slice of that node’s file (see `lens/core/address.py`).

**Options:** `--model` / `-m` (`[[speech]]` id), `--voice` / `-v` (default `eve`), `--language` / `-l` (default `en`), `--silent` — skip `ffplay` after each chunk.

After each chunk is ready, if `ffplay` is on your `PATH` and `--silent` was not passed, Lens runs `ffplay -nodisp -autoexit -i -` (audio piped on stdin).

Requires **`[project] mount_point`** and at least one `[[speech]]` block in `lens.toml` (see **[docs/configuration.md](../../docs/configuration.md)**).

### `lens media composite chromakey`

Removes a chroma-keyed background from an illustration (bordered characters like anime — not photos or semi-transparent subjects) and saves a foreground PNG with an alpha channel, tagged `composite: foreground` (see the `composite` sidecar key documented under [`lens media attach`](#lens-media-attach)). Works best with a flat magenta (`#FF00FF`) background.

The keying math auto-detects the background color and tolerance from the image's corners, but tolerance is the one parameter worth hand-tuning per image. Since the CLI writes straight to the mount, the flow is: run it, look at the saved file, and if the cut isn't clean, re-run with `--core-tol` (each run prints the resolved key/tolerance/dilate values so you know what to override). Re-running against the same destination overwrites it — there's no separate preview step to manage.

```bash
lens media composite chromakey chars/hero.png                             # save chars/hero_fg.png, tag composite: foreground
lens media composite chromakey chars/hero.png --core-tol 30               # not clean? retune and re-run — overwrites hero_fg.png
lens media composite chromakey chars/hero.png --out chars/hero_cut.png    # custom destination
lens media composite chromakey chars/hero.png --key FF00FF --core-tol 30  # skip auto-detection entirely
```

**Positional:** `PATH` — mount-relative path of the chroma-keyed source image.

Options:

- `--key` / `-k` — hex background color to key out (e.g. `FF00FF`); auto-detected from the image corners if omitted.
- `--core-tol` — color-distance tolerance for the confident background core; auto-calibrated if omitted. The one worth hand-tuning on a noisy or unusual input.
- `--residual-thresh` — edge alpha-blend fit tolerance (default `10.0`); rarely needs changing.
- `--dilate-px` — edge zone width in pixels around the background core; auto-scaled to resolution if omitted.
- `--out PATH` — mount-relative destination `.png` path for the saved foreground (default: `<input-stem>_fg.png` next to the source). Re-running with the same destination overwrites it.

**Web UI:** the in-app command bar's `/media-composite chromakey <path>` (with `--key`/`--core-tol`/`--residual-thresh`/`--dilate-px` options, same meanings as above) opens a preview panel instead of saving immediately — it renders the keyed-out image, lets you retune tolerance and re-preview live, and only writes to the mount (tagging `composite: foreground`) when you click Save. Omit `<path>` (or give a folder) to browse the mount and pick a source image instead. The CLI skips that extra step since you can just open the saved file directly.

### Configuring `mount_point`

See **[Configuration — `[project].mount_point`](../../docs/configuration.md#project)** (local vs `s3://`, env vars, attach paths, `--ref` on S3). Use `lens check` to validate.

