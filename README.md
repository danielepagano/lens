# Lens

Filesystem-native, forward-only narrative trees and a knowledge store for modular AI-assisted creation with fractal summarization.

## Overview

Lens is a filesystem-native narrative engine for collaborative AI-assisted storytelling. Stories live in a **fractal tree** of Markdown nodes, grounded in a **knowledge store** (places, people, lore). Humans and AI work via **operators** like `write`, `edit`, `section`, and `collate`; changes are **transactional** (Git unstaged = preview, commit when ready).

- **Forward-only narrative** — Once committed, it’s canon; the system evolves from the current state.
- **Fractal summarization** — High-level nodes summarize detail below so the AI keeps long-term continuity.
- **Knowledge store** — Typed, tag-linked objects the AI can query and pin to narrative nodes.
- **Git-backed** — A Lens project is a Git repo; you can edit the Markdown directly and use Lens for structure and automation.

## Setup

```bash
cd /path/to/lens && poetry install
```

To run `lens` from anywhere: use an in-project venv (`poetry config virtualenvs.in-project true`, then add `.../lens/.venv/bin` to your PATH), or run commands via `poetry -C /path/to/lens run lens <command>`.

## Quick start

```bash
lens init                    # create lens.toml, knowledge/, narrative/
lens use my-campaign          # select (or create) a narrative
lens write "open with a storm"   # AI writes at the cursor
lens kb get person.hero       # fetch from the knowledge store
lens stats                    # list narratives and object counts
```

## Lens API and Web UI

Besides the CLI, a REST server and UI live in `lens/server/`). To start the server from a Lens project directory:

```bash
lens serve    # Build frontend and serve at http://127.0.0.1:8000
lens dev      # Vite dev server with HMR — open http://localhost:5173
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

### `[project]` settings

The `[project]` section in `lens.toml` controls project-level options:

```toml
[project]
narrative    = "my-campaign"   # active narrative (set by `lens use`)
datasets     = ["rpg", "dnd"]  # optional dataset bundles (later shadows earlier)
mount_point  = "media"         # optional: local directory for attached media files
verbose_llm  = true            # optional: log full LLM prompts/responses at INFO level
```

**`mount_point`** — enables the `lens attach` command and the web UI's media browser. Set it to a path relative to the project root (or an absolute path) where you keep images, videos, and documents you want to embed in narrative nodes. The directory is not managed by Lens; organise it however you like. Only files inside this directory can be attached.

**`verbose_llm`** — when `true`, each LLM call emits a `[SYSTEM]` / `[USER]` / `[ASSISTANT]` block to the logger at `INFO` level — showing the exact prompt and full response with no raw protocol noise.

## Dice Rolling

Any prompt sent to an AI operator (`write`, `play`, `edit`, etc.) may include inline dice expressions. These are **evaluated before the prompt reaches the AI** — the AI only ever sees the resolved result, never the `@roll` syntax.

### Syntax

| Form | Example | Use case |
|------|---------|----------|
| `@roll <expr>` | `@roll d20+5` | No spaces in expression |
| `@roll (<expr>)` | `@roll (2d6 + 3)` | Spaces allowed inside parens |

A space after `roll` is required. Spaces within the expression are only allowed in the parenthesised form.

Expressions use standard dice notation powered by [python-dice](https://github.com/borntyping/python-dice):

- `d20`, `2d6`, `4d6h3` — standard dice (h = keep highest)
- `d20+7`, `2d8+1d4+2` — arithmetic
- `2d20h1` — advantage (roll 2d20, keep highest 1)

### Examples

```
/play I try to sneak past the guard — @roll d20+3 stealth check
/write She draws her sword and strikes, @roll (2d6 + 4) slashing damage
/play With advantage: @roll 2d20h1 to hit
```

For tabletop pacing, **`/play … --wait`** (CLI and web UI) appends only the player line; run `/play` again without `--wait` when you want the GM response. See [RPG / play](lens/rpg/README.md).

What the AI receives (rolls already resolved):
```
I try to sneak past the guard — (rolled 17) stealth check
```

### Error handling

If the expression is invalid (e.g. `@roll XYZZY`), the command is aborted and an error is shown to the user. The narrative is never written with an unresolved roll.

### Web UI

Typing `@` in any prompt field shows a purple **⚄ roll** chip as the first autocomplete option. Selecting it inserts `@roll ` (with trailing space). Continue typing the expression (e.g. `d20+5`) or use parens for spaces (e.g. `(2d6 + 3)`). A "dice expression" ghost hint appears while `@roll` is selected and persists while the expression is being typed.

## More Documentation

- **[Design](docs/design.md)** - Lens Design doc
- **[CLI reference](lens/cli/README.md)** — Commands (`kb`, `pin`, `section`), AI operators (`write`, `edit`, `design`), datasets, and LLM configuration.
- **[Web UI & API server](lens/server/README.md)** — `lens serve`, `lens dev`, project/dataset context, and HTTP routes.
- **[RPG](lens/rpg/README.md)** — Core RPG dataset (`play`, `advance`, templates, `rules.rpg`).
- **[D&D](lens/dnd/README.md)** — D&D reference dataset, `lens dnd balance`, and the D&D Beyond extractor.

## Development

Enable browser test with (one time):

```bash
playwright install chromium
```

```bash
poe lint     # Linting
poe pyright  # Type checking
poe test     # Unit tests
poe check    # Lint + typecheck + tests (+ integration)
```
### E2E test infrastructure

Everything under `e2e/` runs against a live, throwaway Lens project wired to
a fake LLM.  No real API key or running server is needed.

**`FakeLLMServer`** (`lens/testing/fake_llm.py`)
An in-process HTTP server that speaks the OpenAI streaming SSE protocol.
Responds to any completion request with Lorem Ipsum followed by
`[input:<N>]` where N is the total character count of the messages — useful
for asserting that context assembly is wiring things up correctly.

```python
with FakeLLMServer() as llm:
    print(llm.base_url)  # http://127.0.0.1:<port>
```

**`setup_test_project()`** (`lens/testing/project.py`)
Creates a fully-populated throwaway project: git repo, `lens.toml` (pointing
at the fake LLM), KB objects (`person.amy`, `place.forest`), and an opening
passage already written by the fake LLM.  Pass `datasets=["rpg", "dnd"]` (keyword)
to enable bundled RPG + D&D knowledge instead of the minimal testing fixtures.

```python
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

with FakeLLMServer() as llm:
    session = setup_test_project(project_dir, llm.base_url, datasets=["rpg", "dnd"])
    # project_dir is a real git repo, ready for CLI or API calls
```

**`e2e/conftest.py`** (session fixtures)
Chains `fake_llm_server` → `lens_project_dir` → `live_server_url` (uvicorn on
a free ephemeral port).  Also exposes `base_url` for Playwright.  Set
`LENS_DEV_SERVER_URL` to bypass server setup and test against a running dev
server instead.

#### External server mode

To run e2e tests against a persistent dev project:

```bash
poe dev  # in one terminal — starts uvicorn + watches the project
LENS_DEV_SERVER_URL=http://127.0.0.1:8000 pytest e2e/
```

The conftest detects the env variable and skips spinning up its own server.