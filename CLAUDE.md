# CLAUDE.md

Agent-oriented grounding for this repository. User-facing docs start at [README.md](README.md); product design at [docs/design.md](docs/design.md).

## Documentation map

| Topic | Location |
|-------|----------|
| Getting started, project layout | [README.md](README.md) |
| Architecture, operators, workflow | [docs/design.md](docs/design.md) |
| `lens.toml`, LLM, mounts, validation | [docs/configuration.md](docs/configuration.md) |
| Testing layers, fake LLM, sandbox, bench | [docs/testing.md](docs/testing.md) |
| CLI commands and operators | [lens/cli/README.md](lens/cli/README.md) |
| Datasets, extensions, sibling layout | [datasets/README.md](datasets/README.md) |
| RPG play (`play`, `advance`, fronts) | [docs/rpg-design.md](docs/rpg-design.md), [datasets/rpg/README.md](datasets/rpg/README.md) |
| Companion chat | [datasets/companion/README.md](datasets/companion/README.md) |
| Server routes, SSE, workflow actions | [lens/server/README.md](lens/server/README.md) |
| Cloud deploy (Fly.io reference), Caddy auth | [deploy/README.md](deploy/README.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Quality runs against real models | [bench/README.md](bench/README.md) |

## Commands

Locally, `poetry` and `poe` are on PATH — use directly. In the cloud
environment (`/home/claude/.ssh/commit_signing_key.pub` exists), `poe` may
not be on PATH; fall back to the full invocation below.

```bash
# Preferred (local dev)
poe check              # lint + types + unit + integration + UI unit + build-ui + e2e
poe lint               # ruff (auto-fix) + eslint + svelte-check + pyright
poe test               # pytest unit tests (core, cli, server, rpg)
poe test-integration   # core integration tests only
poe test-e2e           # full-stack e2e (no browser required for most tests)
poe test-ui            # Vitest (lens/server/ui)
poe build-ui           # vite build → lens/server/static/
poe e2e-sandbox        # manual browser sandbox (temp project + fake LLM)
poe mock-llm           # standalone controllable fake LLM on :18765
poe lens <command>     # run the CLI locally

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
  # also run by poe build-ui / poe test-ui
playwright install chromium          # once, for browser e2e
```

## Definition of done

Always run `poe check` before considering a task complete. It runs lint, typecheck, unit tests, integration tests, UI unit tests, UI build, and e2e tests in sequence — all must pass.

## End-to-end test infrastructure

Full testing map (bench, sandbox, mock LLM, regression fixtures): [docs/testing.md](docs/testing.md).

Everything under `e2e/` exercises the full stack against a real (but
throwaway) Lens project.

```bash
poe test-e2e          # runs all e2e tests (no browser required for most)
pytest e2e/ -n 0 -v   # same, verbose
```

### Building blocks

| Component | Location | Purpose |
|-----------|----------|---------|
| `FakeLLMServer` | `lens/testing/fake_llm.py` | In-process HTTP server that streams Lorem Ipsum as OpenAI-compatible SSE. Start with `.start()`, use `.base_url` in `lens.toml`. Supports stream speed controls (`tokens=`, `tps=`) and special triggers. |
| `setup_test_project()` | `lens/testing/project.py` | Creates a full throwaway Lens project (git repo + `lens.toml` + KB objects + opening passage). Accepts `dataset=` or `datasets=` for `[project] datasets`. Returns a live `ProjectSession`. |
| Regression fixtures | `lens/testing/regression_fixtures.py` | Pre-built project shapes for workflow UI tests (remember, auto-compress, play pins, …). See [e2e/fixtures/README.md](e2e/fixtures/README.md). |
| `e2e/conftest.py` | session fixtures | Wires `fake_llm_server` → `lens_project_dir` → `live_server_url` (uvicorn on a free port). Also sets `base_url` for Playwright. Supports `LENS_DEV_SERVER_URL` env override to test against a running dev server. |

### Test files

- **`e2e/tests/test_api_smoke.py`** — API tests using plain `urllib.request`. Covers `/health`, `/stats`, `/narrative/tree`, `/narrative/node/<name>`.
- **`e2e/tests/test_cli.py`** — CLI tests with `rpg` dataset. Runs `lens stats`, `lens kb get/with-tag`, and `lens write` as subprocesses.
- **`e2e/tests/test_browser.py`** — Playwright UI tests. Auto-skipped when Chromium is not installed.
- **`e2e/tests/test_regression_cli.py`** — CLI+git regression cases (transactions, auto-compress, `@var` / `@roll`).
- **`e2e/tests/test_regression_browser.py`** — Workflow UI regression (step strip, skip/retry, transaction diff).
- **`e2e/tests/test_bench_regression.py`** — Bench scenario file contract smoke.

### Using `setup_test_project` in new tests

```python
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

with FakeLLMServer() as llm:
    project_dir = Path(tempfile.mkdtemp())
    session = setup_test_project(project_dir, llm.base_url, datasets=["rpg"])
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

Lens is a CLI-first system for AI-assisted narrative creation. A **Lens project** is a Git repository with a `lens.toml`, `narrative/`, and `knowledge/` directory. Optional binary assets live on a **media mount** outside git (see [docs/configuration.md](docs/configuration.md)).

### Package layout

```
lens/
  cli/           # Typer CLI layer (argument parsing, error display)
    main.py      # Entry point + preflight callback
    commands/    # Non-AI commands (init, use, kb, pin, stats, rollback, commit, checkpoint, rewind, refresh, media; dataset extensions may add more)
    operators/   # AI operator CLI adapters (write, edit, section, collate, compress, chat, play, design, advance)
    test/        # CLI unit tests
  core/          # Business logic (no Typer dependency)
    project.py   # Git/project root discovery, active narrative resolution, dataset path resolution
    narrative.py # NarrativeNode tree model, NodeSegment, parse_segments()
    annotations.py # Markdown comment-style annotation parsing
    operator.py  # Operator base class + ContextAwareOperator (LLM flow + tool use)
    context.py   # crawl() + assemble_prompt() for LLM context assembly
    llm_run.py   # LlmRun envelope: gather → transform → generate → persist
    prompt_transforms.py # @ prompt orchestration (STORABLE / FLAT); graph transforms in crawl_transforms.py
    workflow_runner.py # Multi-step operator scheduling (generate→auto_compress, summarize→remember)
    hooks.py     # post_inline (auto-compress), summarize_close (remember)
    knowledge.py # KnowledgeStore + KnowledgeObject (filesystem KB)
    pinning.py   # Front matter kb_pin/kb_unpin manipulation
    storage.py   # Storage: git-backed transactional file writes
    address.py   # NarrativeAddress: typed path + line + operator location
    llm.py       # OpenAI-compatible LLM client (streaming + tool calls)
    tools.py     # OperatorToolDef + tool registry (operators as LLM tools)
    command_tools.py # Inline KB lookup tools callable mid-LLM-generation (design uses these)
    dataset_extensions.py # Load optional Python from active datasets ([dataset] extension)
    prompts.py   # Prompt pack resolution (default.toml, dataset prompts.toml, project overrides)
    chain.py     # ChainSpec: deferred operator chaining within a transaction
    exceptions.py # Shared exception types
    commands/    # Core implementations for non-operator commands
    operators/   # Core AI operators (write, edit, section, collate, compress, chat, design)
    test/        # Core unit tests
      integration/  # Integration tests
  rpg/           # Bundled rpg dataset operators (play, advance)
    operators/
    test/
  server/        # FastAPI adapter + Svelte UI (lens/server/ui/)
    test/
  testing/       # Fake LLM, setup_test_project, e2e sandbox, regression fixtures
datasets/
  testing/       # Minimal dataset for integration tests (+ lens_testing_ext extension fixture)
  rpg/           # Core RPG bundle (rules.rpg, rules.system stub, templates, design/*)
  companion/     # Companion chat bundle (see datasets/companion/README.md)
docs/            # Design, configuration, testing, rpg-design
bench/           # Quality runs against real LLMs
e2e/             # Full-stack tests
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

**Operator** (`operator.py`): abstract base for LLM operators. Operating modes:
- *Inline* (`write`, `play`, one-shot `chat`): open tag + streamed content + close tag appended to cursor node
- *Sub-node / session* (`section`, `chat --with`, `play`, `design`, `advance`): creates a child node until `--end` summarizes back
- *Mutation* (`edit`): wraps a line range in staged claim tags; proposes replacement as unstaged diff
- *Structure* (`collate`, `compress`): refactor prose into hierarchy or AI-select a collate range

Operators can register themselves as **LLM tools** via `tools.py` (`register_operator_tool`, `OperatorToolDef`). When the active session includes a dataset that unlocks an operator-tool, the LLM can invoke other operators as tool calls mid-response. Tool calls are dispatched by the `operator.py` loop and share the same storage transaction.

**Command tools ≠ operators.** Small helpers the model may call *inside* one generation loop — read-only KB lookups during `design` (`kb_get`, `kb_list_tags`, `kb_with_tag`), or whitelisted `kb_patch` during remember. They do not spawn other operators.

**Multi-step workflows** (`workflow_runner.py`): session close, auto-compress, and remember are follow-up LLM passes under one user invocation. The runner exposes a step plan (generate → auto_compress, summarize → remember → close). **Skip** declines optional tail steps; **Abort/Cancel** rolls back dirty in-flight steps. See [docs/design.md](docs/design.md) for skip vs abort semantics.

**Context assembly** (`context.py`): `crawl()` collects `kb_pin`/`kb_unpin` from ancestor front matters (walking from root to cursor), resolves linked KB objects, then passes everything to `assemble_prompt()` which formats `[RELEVANT KNOWLEDGE]`, `[PREVIOUS EVENTS SUMMARY]`, `[CURRENT PASSAGE]`, and `[TASK]` blocks into `[system, user]` messages. KB pins resolve on the full ancestor chain; narrative slices follow the lineage spine (fractal summaries).

**KnowledgeStore** (`knowledge.py`): flat key-value store at `knowledge/{type}/{key}.md`. IDs are dot-separated lowercase (`person.amy`). Tags stored in `knowledge/tags.toml` with bidirectional index. The `+` suffix on an ID in a pin expands to linked objects (those sharing a dot-tag pointing to another KB object).

### Operators (implemented)

| Operator | Shape | Location | Notes |
|----------|-------|----------|-------|
| `write` | inline | `core/operators/write.py` | General prose at cursor |
| `edit` | mutation | `core/operators/edit.py` | LLM rewrite of a line range |
| `section` | sub-node | `core/operators/section.py` | Start/end section; `--end` summarizes to parent |
| `collate` | structure | `core/operators/collate.py` | Create section from completed prose range |
| `compress` | structure | `core/operators/compress.py` | AI-select collate range from natural-language prompt |
| `chat` | inline / session | `core/operators/chat.py` | In-character speech (`--as`, optional `--with` session) |
| `design` | session | `core/operators/design.py` | Session Zero planning; uses command_tools; emits fenced `kb` blocks |
| `play` | session | `rpg/operators/play.py` | GM-voice narrative; requires `rpg` dataset + pinned `pc.*` |
| `advance` | session | `rpg/operators/advance.py` | Time pass / fronts; requires `rpg` dataset |

### LLM configuration

Configured in the content repo's `lens.toml`, not in this repo. Full reference: [docs/configuration.md](docs/configuration.md) (`[[llm]]`, `extra_headers` / `extra_payload`, `[operator.*]`, image/speech, compress, params, deployment). Uses OpenAI-compatible API. First `[[llm]]` entry is the default; others require explicit `--llm <id>`. The `api_key_env` field names an environment variable holding the key (never stored in toml).

Prompt text is layered: bundled defaults (`lens/prompts/default.toml`), dataset `prompts/prompts.toml`, project overrides (`prompts/prompts.toml`, copy-on-write). Operators reference keys via `prompts.py`, not hardcoded prose.

### Datasets

Read-only knowledge stores bundled with the Lens tool, declared in `lens.toml` under `[project] datasets = [...]`. Later entries shadow earlier ones; project-local items always win. Mutating a dataset object creates a project-local copy (copy-on-write).

- `datasets/testing/` — minimal test fixtures + `lens_testing_ext` extension for unit tests
- `datasets/rpg/` — Core RPG bundle: `rules.rpg`, `rules.system` stub, templates, `design/*`; operators `play`/`advance` live in `lens/rpg/`
- `datasets/companion/` — Companion chat templates and meta pins
- Other dataset names resolve from a sibling repo or `lens.local.toml` — see [datasets/README.md](datasets/README.md)

**Dataset extensions** (`dataset_extensions.py`): when a dataset's `lens.toml` declares `[dataset] extension = "pkg"` (or `pkg:register`), Lens loads that Python package from the dataset directory on CLI/server startup. Extensions can register CLI command groups and LLM command tools. Example: private `lens-dnd` repo with `lens dnd balance` — not bundled in Lens. Bundled `rpg` operators remain in `lens/rpg/`, not via extension.

### Server (`lens/server/`)

The server is a FastAPI adapter over `lens/core/`. CLI and server are sibling interfaces — both are thin adapters; all business logic lives in `core/`.

**Critical rules:**
- Routes validate input (Pydantic), call core functions, and map domain exceptions to HTTP errors. No business logic in routes.
- `server/` imports only from `core/`, never from `cli/`.
- Core is synchronous. Do not make core code async. Use `run_in_threadpool` only at the route boundary if truly needed. Async is contagious — contain it at the edges.
- Core must raise explicit exceptions, not call `sys.exit()` or `print()`.
- Routes must catch domain exceptions and return HTTP 400/500. Stack traces must not leak to clients.
- One SSE stream at a time per project (enforced via `app.state.stream_locks`). New streaming routes must acquire the same lock.
- Workflow actions: `POST /{slug}/stream/workflow/action` with `{step_id, action: "skip"|"retry"}`.

**Authentication:** Handled entirely at the Caddy reverse proxy layer. FastAPI trusts all incoming requests as authenticated. Do not add auth logic to routes. If Caddy is removed, the server must not be exposed to the public internet.

**Static frontend:** In production, `vite build` output is served by FastAPI from `server/static/`. Frontend and API share the same origin — no CORS needed.

### Frontend (`lens/server/ui/`)

Svelte + Vite + Pico.css + CodeMirror 6 + markdown-it. No additional frameworks or UI libraries.

**Hard constraints (architecture violations must be rejected):**
1. No component should grow without bound: ~300 lines is the usual target; **split when a file passes ~450 lines** or mixes unrelated concerns. Single-purpose components in the ~300–450 range are acceptable.
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
- During generation, show workflow step plan with Skip on optional steps and Retry/Skip on retryable failures — not a single "streaming…" label.
- If a 401 is received, treat it as fatal; let the browser re-authenticate via HTTP Basic challenge. Do not implement login UI or handle 401 programmatically.
