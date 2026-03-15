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

### Verbose LLM logging

To log full prompts and responses in a human-readable format (useful for debugging operator output), add `verbose_llm = true` to the `[project]` section:

```toml
[project]
narrative    = "my-campaign"
verbose_llm  = true
```

With this enabled, each LLM call will emit a `[SYSTEM]` / `[USER]` / `[ASSISTANT]` formatted block to the logger at `INFO` level — showing the exact prompt sent and the full response received, with no raw protocol noise.

## More Documentation

- **[Design](docs/design.md)** - Lens Design doc
- **[CLI reference](lens/cli/README.md)** — Commands (`kb`, `pin`, `section`), AI operators (`write`, `edit`, `design`), datasets, and LLM configuration.
- **[Web UI & API server](lens/server/README.md)** — `lens serve`, `lens dev`, project/dataset context, and HTTP routes.
- **[D&D](lens/dnd/README.md)** — D&D dataset, `lens dnd balance`, `lens play`, and the D&D Beyond extractor.

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
passage already written by the fake LLM.  Pass `dataset="dnd"` to enable the
D&D dataset instead of the minimal testing fixtures.

```python
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

with FakeLLMServer() as llm:
    session = setup_test_project(project_dir, llm.base_url, dataset="dnd")
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