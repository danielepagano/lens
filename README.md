# Lens

Filesystem-native, forward-only narrative trees and a knowledge store for modular AI-assisted creation with fractal summarization.

## Overview

Lens is a filesystem-native narrative engine for collaborative AI-assisted storytelling. Stories live in a **fractal tree** of Markdown nodes, grounded in a **knowledge store** (places, people, lore). Humans and AI work via **operators** like `write`, `edit`, and `section`; changes are **transactional** (Git unstaged = preview, commit when ready).

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
- **[API server](lens/server/README.md)** — `lens serve`, project/dataset context, and HTTP routes.
- **[D&D](lens/dnd/README.md)** — D&D dataset, `lens dnd balance`, `lens play`, and the D&D Beyond extractor.

## Development

```bash
poe lint     # Linting
poe pyright  # Type checking
poe test     # Unit tests
poe check    # Lint + typecheck + tests (+ integration)
```
