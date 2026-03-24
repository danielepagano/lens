# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Locally, `poetry` and `poe` are on PATH — use directly. In the cloud
environment (`/home/claude/.ssh/commit_signing_key.pub` exists), `poe` may
not be on PATH; fall back to the full invocation below.

```bash
# Preferred (local dev)
poe check     # lint + typecheck + unit tests + integration tests + e2e
poe lint      # ruff (auto-fix) + pyright + eslint
poe test      # pytest unit tests
poe lens <command>  # run the CLI locally

# Cloud fallback (poe not on PATH)
POETRY=/root/.local/share/uv/tools/poetry/bin/poetry
$POETRY run poe check

# Run a single test module
python -m pytest lens/core/test/test_annotations.py -v

# Run a single test method
python -m pytest lens/core/test/test_annotations.py -v -k test_method_name

# Manual dependency install (done automatically by session-start hook)
poetry install
cd lens/server/ui && npm install
```

## Definition of done

Always run `poe check` before considering a task complete. It runs lint, typecheck, unit tests, integration tests, and e2e tests in sequence — all must pass.

## End-to-end test infrastructure

Everything under `e2e/` exercises the full stack against a real (but
throwaway) Lens project.

```bash
poe test-e2e          # runs all e2e tests (no browser required)
pytest e2e/ -n 0 -v   # same, verbose
```

### Building blocks

| Component | Location | Purpose |
|-----------|----------|---------|
| `FakeLLMServer` | `lens/testing/fake_llm.py` | In-process HTTP server that streams Lorem Ipsum as OpenAI-compatible SSE. Start with `.start()`, use `.base_url` in `lens.toml`. |
| `setup_test_project()` | `lens/testing/project.py` | Creates a full throwaway Lens project (git repo + `lens.toml` + KB objects + opening passage). Accepts `dataset=` or `datasets=` for `[project] datasets`. Returns a live `ProjectSession`. |
| `e2e/conftest.py` | session fixtures | Wires `fake_llm_server` → `lens_project_dir` → `live_server_url` (uvicorn on a free port). Also sets `base_url` for Playwright. Supports `LENS_DEV_SERVER_URL` env override to test against a running dev server. |

### Test files

- **`e2e/tests/test_api_smoke.py`** — API tests using plain `urllib.request`. Covers `/health`, `/stats`, `/narrative/tree`, `/narrative/node/<name>`.
- **`e2e/tests/test_cli.py`** — CLI tests with `rpg` + `dnd` datasets. Runs `lens stats`, `lens kb get/with-tag`, and `lens write` as subprocesses. Module-scoped `dnd_project` fixture uses `setup_test_project(..., datasets=["rpg", "dnd"])`.
- **`e2e/tests/test_browser.py`** — Playwright placeholder. Auto-skipped when Chromium is not installed. Run `playwright install chromium` to enable.

### Using `setup_test_project` in new tests

```python
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

with FakeLLMServer() as llm:
    project_dir = Path(tempfile.mkdtemp())
    session = setup_test_project(project_dir, llm.base_url, datasets=["rpg", "dnd"])
    # project_dir is a real git repo with lens.toml, narrative, KB, written passage
```

The fake LLM always responds with Lorem Ipsum followed by `[input:<N>]` where N
is the total character count of the messages sent — useful for verifying context
assembly.

## Cloud environment (Claude Code on claude.ai)

Cloud sessions enforce signed git commits via a hook that calls an external
API (`/tmp/code-sign`).  `poe test` and `poe check` work correctly because
`lens/conftest.py` detects the environment at session start and injects
`GIT_CONFIG_COUNT` overrides that disable signing for all subprocess git calls
made during the pytest session.

**How to detect a cloud session**: `/home/claude/.ssh/commit_signing_key.pub`
exists.  Alternatively: `git config --global commit.gpgsign` returns `true`
with `gpg.ssh.program` pointing to `/tmp/code-sign`.

## Architecture

Lens is a CLI tool for managing AI-assisted narrative creation. A **Lens project** is a Git repository with a `lens.toml`, `narrative/`, and `knowledge/` directory.

### Package layout

```
lens/
  cli/           # Typer CLI layer (argument parsing, error display)
    main.py      # Entry point + preflight callback
    commands/    # Non-AI commands (init, use, kb, pin, stats, rollback, commit, checkpoint, dnd)
    operators/   # AI operator CLI adapters (write, edit, section, collate, play, design)
    test/        # CLI unit tests
  core/          # Business logic (no Typer dependency)
    project.py   # Git/project root discovery, active narrative resolution
    narrative.py # NarrativeNode tree model, NodeSegment, parse_segments()
    annotations.py # Markdown comment-style annotation parsing
    operator.py  # Operator base class + ContextAwareOperator (LLM flow + tool use)
    context.py   # crawl() + assemble_prompt() for LLM context assembly
    knowledge.py # KnowledgeStore + KnowledgeObject (filesystem KB)
    pinning.py   # Front matter kb_pin/kb_unpin manipulation
    storage.py   # Storage: git-backed transactional file writes
    address.py   # NarrativeAddress: typed path + line + operator location
    llm.py       # OpenAI-compatible LLM client (streaming + tool calls)
    tools.py     # OperatorToolDef + tool registry (operators as LLM tools)
    command_tools.py # Inline KB lookup tools callable mid-LLM-generation (design uses these)
    chain.py     # ChainSpec: deferred operator chaining within a transaction
    exceptions.py # Shared exception types
    commands/    # Core implementations for non-operator commands
    operators/   # Core implementations for AI operators (write, edit, section, collate, design)
    test/        # Core unit tests
      integration/  # Integration tests
  rpg/           # Core RPG dataset package (play, advance operators)
    operators/
    test/
  dnd/           # D&D dataset package (balance_encounter command + tool)
    commands/
    test/
datasets/
  testing/       # Minimal dataset for integration tests
  rpg/           # Core RPG bundle (rpg, system stub, templates, design modules)
  dnd/           # D&D 2024 reference (rules/system override, spell, stat, equipment)
tools/
  ddb-extract/   # TypeScript CLI: extracts D&D Beyond content into KB Markdown files
```

Every command/operator has a parallel `cli/` adapter (Typer plumbing) and a `core/` implementation (reusable logic). Always put business logic in `core/`.

### Key data model

**NarrativeNode** (`narrative.py`): a node in the tree, backed by either a leaf file (`narrative/<name>/<key>.md`) or a folder node (`narrative/<name>/<key>/_node.md`). The cursor position is tracked by the last unclosed single-line annotation at the tail of a node file.

**Annotations** (`annotations.py`): operator state is stored as markdown reference-style comments. Single-line: `[operator:id]: #`. Multi-line (with YAML params):
```
[write
  prompt: continue the story
  steps: 1
]: #
```
Closing tags: `[/section:ch1]: #`. Self-closing: `[section:ch1/]: #`.

**Storage + transactions** (`storage.py`): every write goes through `Storage`, which is instantiated with an owner `NarrativeAddress`. On the first write, if unstaged changes exist from a *different* owner, they are auto-staged first. This enforces single-pending-transaction semantics. Git's unstaged area = pending transaction; `git add -A` = commit transaction.

**Operator** (`operator.py`): abstract base for LLM operators. Provides three operating modes:
- *Inline* (`write`, `play`): open tag + streamed content + close tag appended to cursor node
- *Sub-node* (`section`): creates a child node, appends open tag to parent
- *Mutation* (`edit`): wraps a line range in staged claim tags; proposes replacement as unstaged diff

Operators can register themselves as **LLM tools** via `tools.py` (`register_operator_tool`, `OperatorToolDef`). When the active session includes a dataset that unlocks an operator-tool, the LLM can invoke other operators as tool calls mid-response. Tool calls are dispatched by the `operator.py` loop and share the same storage transaction. Operators can also **chain** to another operator on completion via `chain.py` (`ChainSpec`) — chained operators inherit the same storage transaction.

**`play` operator** (`rpg/operators/play.py`): GM-voice narrative operator. Requires at least one `pc.*` KB object pinned; GM voice without narrating PC decisions. Dataset-gated: `rpg` in `lens.toml`. Pins `rules.system` + `rules.rpg`.

**Context assembly** (`context.py`): `crawl()` collects `kb_pin`/`kb_unpin` from ancestor front matters (walking from root to cursor), resolves linked KB objects, then passes everything to `assemble_prompt()` which formats `[RELEVANT KNOWLEDGE]`, `[PREVIOUS EVENTS SUMMARY]`, `[CURRENT PASSAGE]`, and `[TASK]` blocks into `[system, user]` messages.

**KnowledgeStore** (`knowledge.py`): flat key-value store at `knowledge/{type}/{key}.md`. IDs are dot-separated lowercase (`person.amy`). Tags stored in `knowledge/tags.toml` with bidirectional index. The `+` suffix on an ID in a pin expands to linked objects (those sharing a dot-tag pointing to another KB object).

### LLM configuration

Configured in the content repo's `lens.toml`, not in this repo. Uses OpenAI-compatible API. First `[[llm]]` entry is the default; others require explicit `--llm <id>`. The `api_key_env` field names an environment variable holding the key (never stored in toml).

### Datasets

Read-only knowledge stores bundled with the Lens tool, declared in `lens.toml` under `[project] datasets = [...]`. Later entries shadow earlier ones; project-local items always win. Mutating a dataset object creates a project-local copy (copy-on-write).

- `datasets/testing/` — minimal test fixtures used by the test suite
- `datasets/rpg/` — Core RPG bundle: `rules.rpg`, `rules.system` stub, templates, `design/*`. 
- `datasets/dnd/` — D&D 2024 reference: `rules/system.md` (overrides), `spell/`, `stat/`, `equipment/`, `tags.toml`. Populated via `tools/ddb-extract/` + `lens kb extract`.

### Tools

`tools/ddb-extract/` is a standalone TypeScript CLI (Playwright + CDP) that extracts D&D Beyond content into Lens KB-formatted Markdown files. Run `npm install` inside the directory, then invoke via `tsx src/cli.ts`. See `tools/ddb-extract/README.md`. The `ddb-extract-design.md` in `docs/` describes the original design (may be removed).

### Server (`lens/server/`)

The server is a FastAPI adapter over `lens/core/`. CLI and server are sibling interfaces — both are thin adapters; all business logic lives in `core/`.

**Critical rules:**
- Routes validate input (Pydantic), call core functions, and map domain exceptions to HTTP errors. No business logic in routes.
- `server/` imports only from `core/`, never from `cli/`.
- Core is synchronous. Do not make core code async. Use `run_in_threadpool` only at the route boundary if truly needed. Async is contagious — contain it at the edges.
- Core must raise explicit exceptions, not call `sys.exit()` or `print()`.
- Routes must catch domain exceptions and return HTTP 400/500. Stack traces must not leak to clients.
- One SSE stream at a time (enforced via `app.state.stream_lock`). New streaming routes must acquire the same lock.

**Authentication:** Handled entirely at the Caddy reverse proxy layer. FastAPI trusts all incoming requests as authenticated. Do not add auth logic to routes. If Caddy is removed, the server must not be exposed to the public internet.

**Static frontend:** In production, `vite build` output is served by FastAPI from `server/static/`. Frontend and API share the same origin — no CORS needed.

### Frontend (`lens/server/ui/`)

Svelte + Vite + Pico.css + CodeMirror 6 + markdown-it. No additional frameworks or UI libraries.

**Hard constraints (architecture violations must be rejected):**
1. No component may exceed ~300 lines.
2. CodeMirror is configured only in the editor component — nowhere else.
3. Network logic (fetch, EventSource) lives only in `services/` — never in components.
4. Global state lives only in `stores/` — never derived or duplicated in components.
5. Layout structure is defined in `MainLayout.svelte` and must not be redefined by feature code.
6. No inline `innerHTML` manipulation outside the markdown renderer (`MarkdownView.svelte`).
7. No feature may reach into another feature's internal implementation.
8. Always use narrative address paths (e.g. `/chapter-1`) for node identification — never internal IDs.

**UX rules:**
- No git terminology in the UI. Use "Checkpoint" not "Push", "Save" not "Commit", "Discard" not "Rollback".
- Unstaged changes must be visually distinct (badge, border, or background indicator).
- On page load/refresh, fetch current project state (including cursor) from the backend — do not rely on client-side routing or cached state.
- If a 401 is received, treat it as fatal; let the browser re-authenticate via HTTP Basic challenge. Do not implement login UI or handle 401 programmatically.
