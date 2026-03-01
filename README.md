# Lens

Filesystem-native, forward-only narrative trees and a knowledge store for modular AI-assisted creation with fractal summarization.

## Overview

Lens is a filesystem-native narrative engine designed for collaborative AI-assisted storytelling. It enables the creation of complex "narrative simulations"—prose stories grounded in a persistent knowledge store and structured into a fractal, multi-layered tree.

### Core Concepts

*   **Forward-Only Narrative**: Narrative is created in a forward-only fashion. Once committed, it becomes canon. While the past can be changed via Git history, the system is designed to support the evolution of the story from its current state.
*   **Fractal Summarization**: The story is hierarchical and fractal. A high-level node can contain a summary of a detailed event, which in turn might contain even more granular beats. This allows the AI to maintain long-term continuity by looking at ancestor summaries (lower resolution for distant facts) while remaining grounded in the immediate context.
*   **Knowledge Store**: A persistent key-value store of "facts" (places, people, lore) that grounds the narrative. Objects are classified by type and can be interconnected via a flexible tagging system, creating a rich knowledge graph that the AI can traverse.
*   **Operators & Transactions**: Humans and AIs collaborate using an extensible set of **Operators** (like `write`, `edit`, and `section`).
    *   **Composable**: Operators are naturally composable. You can open a `section` and, within it, use `write` to generate content or open further nested sections.
    *   **Transactional**: Every change is a transaction. Lens uses Git's unstaged area as a "preview" state. You can review AI output, retry with new instructions, or use `lens rollback` to discard changes and restore the previous state.
*   **Git-Backed Storage**: A Lens project is a Git repository. This acts as the database, tracking every change to the narrative and knowledge over time. You can read and edit the Markdown files directly, while Lens provides the automation and structure to manage the complexity.

## Setup

```bash
cd /path/to/lens && poetry install
```

To run `lens` from any directory (e.g. your content repos):

**Option A — In-project venv + PATH** (recommended):

Poetry uses a global venv cache by default. Create an in-project venv so the path is stable:

```bash
cd /path/to/lens
poetry config virtualenvs.in-project true
poetry install
```

Then add to your `~/.zshrc`:
```bash
export PATH="/path/to/lens/.venv/bin:$PATH"
```

**Option B — Use Poetry's venv path** (if you didn't use in-project):

```bash
poetry -C /path/to/lens env info
```
Add the `Path` + `/bin` to your PATH (e.g. `.../lens-LtL4t6e--py3.14/bin`). Note: this path can change if Poetry recreates the venv.

**Option C — Use poetry -C** (no PATH change):
```bash
poetry -C /path/to/lens run lens init
```

## Usage

1. Create a git repo with your lens project data
2. Initialize the Lens project (creates `lens.toml`, `knowledge/`, `narrative/`, etc.):

```bash
lens init
```
3. Select a narrative (creates the folder and root `_node.md` if needed):

```bash
lens use my-campaign
```
4. Run lens commands!

```bash
lens stats      # count objects and list narratives (-v for transaction diffs)
lens kb         # knowledge store (see lens kb --help)
lens section    # start/end sections, or carve one from existing prose
lens pin        # pin/unpin knowledge objects to nodes (see lens pin --help)
lens write      # AI: generate narrative text at the cursor
lens edit       # AI: rewrite a selected line range
lens rollback   # discard or compensate a pending operator transaction
lens commit     # commit the transaction (i.e. stage all files)
lens checkpoint # commit committed changes; tries to push, optional commit message
```

### Knowledge store (`lens kb`)

| Command   | Purpose                          |
|-----------|----------------------------------|
| `add`     | Create or update objects         |
| `get`     | Fetch objects (append `!` for linked) |
| `template`| Manage type templates            |
| `tag`     | Add/remove tags on objects       |
| `delete`  | Delete object and its references |
| `copy`    | Copy object to a new ID (any type) |
| `rename`  | Rename object to a new ID (any type) |

Run `lens kb <command> --help` for details. Note that all KB ID's an tags normalize to lowercase.

### KB Datasets

Datasets are read-only knowledge stores bundled with the Lens tool. They let you share common knowledge — rules, templates, world-building lore — across many projects without copying files into each one.

#### Importing a dataset

Add a `datasets` list to the `[project]` section of your `lens.toml`:

```toml
[project]
narrative = "my-campaign"
datasets  = ["testing"]          # one or more dataset names
```

Datasets are resolved in order: **later entries shadow earlier ones**, and **project-local items always win** over any dataset. So you can import a dataset and safely override individual objects by creating a project-local copy.

#### Lookup and copy-on-write

When Lens looks up a KB object it searches the project first, then each dataset in the order listed (last wins for conflicts). This means you can `lens kb get`, `lens pin add`, or reference any dataset object exactly as if it were a project-local object — no explicit import step required.

Mutating a dataset object (`lens kb tag`, `lens kb add`, etc.) automatically creates a **project-local copy** first and applies the change there. The original dataset file is never modified.

```bash
# Dataset item "person.hero" becomes visible automatically:
lens kb get person.hero

# Tagging it creates a local copy in knowledge/person/hero.md:
lens kb tag person.hero --add featured

# Explicitly copy a dataset item into the project under a new ID:
lens kb copy person.hero person.custom-hero
```

Deleting a dataset-only object is a **no-op** — dataset items are immutable from the project's perspective. If you previously created a project-local copy of a dataset object, deleting that local copy is allowed (and will reveal the original dataset version again).

#### Available datasets

| Name | Description |
|------|-------------|
| `testing` | Minimal dataset used by the Lens integration test suite. |

### Knowledge pins (`lens pin`)

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

### Sections (`lens section`)

Sections structure the narrative tree by creating child nodes under the cursor.

```bash
lens section start intro   # create child node "intro" and open section tag
lens section end           # close the current section (appends summary to parent)
```

A section creates a `[section:id]: #` annotation in the parent node and moves the cursor into the new child. `lens section end` appends a summary and the closing tag, then moves the cursor back up.

#### Front matter pins

Use `--pin` and `--unpin` when starting a section to set the child node's front matter. Any operator running in that section (write, play, etc.) will inherit these pins:

```bash
lens section start castle-dorn -p location.castle-dorn -p faction.dorn-court! -u location.capital-city
```

- `-p` / `--pin` — KB ID to pin (repeatable). Add `!` to include linked objects.
- `-u` / `--unpin` — KB ID to unpin (repeatable), cancelling an ancestor pin.

#### After-the-fact sectioning

You can also carve a section out of already-written prose by specifying a line range:

```bash
lens section range intro /chapter-1 10 30
```

Arguments: `ID ADDRESS START_LINE END_LINE`

- `ID` — key for the new child node (must not already exist).
- `ADDRESS` — narrative node address (e.g. `/chapter-1`, `my-story/chapter-1`).
- `START_LINE` / `END_LINE` — 1-based, inclusive line range to extract.

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

Proposes an LLM rewrite of a specific line range in a node, staging a claim annotation.

```bash
lens edit /chapter-1 10 20 "make it more tense"
lens edit /chapter-1 10 20 --retry            # regenerate with same instruction
lens edit /chapter-1 10 20 "shorter"          # regenerate with new instruction
lens edit /chapter-1 10 20 "fix it" -p place.inn
```

Arguments: `ADDRESS START_LINE END_LINE [PROMPT]`

- `ADDRESS` — narrative node address (e.g. `/chapter-1`, `my-story/chapter-1`).
- `START_LINE` / `END_LINE` — 1-based, inclusive line range to rewrite.
- `PROMPT` — editing instruction (required for a fresh edit; optional on retry to reuse the previous instruction).

`edit` wraps the selected lines in a claim annotation (`[edit:eSTART_END]: #`) that is staged, then streams the proposed replacement as an unstaged diff. Use `lens rollback` to cancel, or commit to accept.

### `lens rollback`

Discards the pending operator transaction. The behaviour differs by operator type:

- **Inline operators** (`write`): unstaged changes are discarded (`git checkout -- .`).
- **Mutation operators** (`edit`): a *compensating transaction* is applied — the staged claim tags are removed and the original text is restored, leaving no trace of the operator in the history.

```bash
lens rollback        # prompts for confirmation
lens rollback --yes  # skip confirmation
lens rollback -y     # shorthand
```

## LLM Configuration

Lens uses LLM APIs (OpenAI-compatible) for AI operators like `write` and `edit`. Configure them in your project's `lens.toml`.

### Adding an LLM

Add one or more `[[llm]]` entries. The **first entry is the default**; the rest are only used if explicitly selected by `id`.

```toml
[[llm]]
base_url         = "https://api.openai.com/v1"
model            = "gpt-4o"
api_key_env      = "OPENAI_API_KEY"   # env var that holds the API key
temperature      = 0.8                # optional, default 0.8
timeout_seconds  = 120                # optional, default 120

[[llm]]
id               = "fast"             # optional name for non-default models
base_url         = "https://api.openai.com/v1"
model            = "gpt-4o-mini"
api_key_env      = "OPENAI_API_KEY"
```

`api_key_env` names the environment variable that holds the API key — credentials are never stored in `lens.toml`. If the variable is unset at runtime, Lens will report a clear error.

Any OpenAI-compatible endpoint works (e.g. Anthropic via openai-compat proxy, Ollama, Together AI, etc.) — just set `base_url` accordingly.

### Verbose LLM logging

To log full prompts and responses in a human-readable format (useful for debugging operator output), add `verbose_llm = true` to the `[project]` section:

```toml
[project]
narrative    = "my-campaign"
verbose_llm  = true
```

With this enabled, each LLM call will emit a `[SYSTEM]` / `[USER]` / `[ASSISTANT]` formatted block to the logger at `INFO` level — showing the exact prompt sent and the full response received, with no raw protocol noise.

## Development

```bash
poe lint     # Linting
poe pyright  # Type checking
poe test     # Run tests

poe check    # All of the above at once!
```
