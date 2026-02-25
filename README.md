# Lens

Filesystem-native, forward-only narrative trees and a knowledge store for modular AI-assisted creation with fractal summarization.

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
lens stats   # counts objects and lists narratives
lens kb      # knowledge store commands (see lens kb --help)
lens section # start and end sections
lens pin     # pin/unpin knowledge objects to nodes (see lens pin --help)
```

### Knowledge store (`lens kb`)

| Command   | Purpose                          |
|-----------|----------------------------------|
| `store`   | Create or update objects         |
| `template`| Manage type templates            |
| `tags`    | Add/remove tags on objects       |
| `delete`  | Delete object and its references |
| `get`     | Fetch objects (append `!` for linked) |

Run `lens kb <command> --help` for details.

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

## LLM Configuration

Lens uses LLM APIs (OpenAI-compatible) for AI operators like `write` and `summarize`. Configure them in your project's `lens.toml`.

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
