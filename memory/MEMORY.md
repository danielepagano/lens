# Lens Project Memory

Concise facts for agents. Full grounding: [CLAUDE.md](../CLAUDE.md). Product design: [docs/design.md](../docs/design.md).

## Doc quick links

| Need | Read |
|------|------|
| Commands, operators, pins | [lens/cli/README.md](../lens/cli/README.md) |
| `lens.toml`, LLM, mounts | [docs/configuration.md](../docs/configuration.md) |
| Testing, fake LLM, sandbox | [docs/testing.md](../docs/testing.md) |
| Datasets, extensions | [datasets/README.md](../datasets/README.md) |
| RPG play | [docs/rpg-design.md](../docs/rpg-design.md) |
| Server/SSE routes | [lens/server/README.md](../lens/server/README.md) |

## Architecture

- **CLI** (`lens/cli/`, Typer) and **server** (`lens/server/`, FastAPI) are thin adapters over **core** (`lens/core/`, pure Python, no Typer).
- Every command has parallel `cli/` adapter + `core/` implementation — business logic always in `core/`.
- Bundled RPG operators (`play`, `advance`) live in `lens/rpg/`, not via dataset extension.
- Optional dataset Python (CLI groups, command tools) loads via `lens/core/dataset_extensions.py` when `[dataset] extension` is set.
- D&D tools live in private `lens-dnd` sibling repo — not in Lens.

## Operators (implemented)

| Operator | Mode | Package |
|----------|------|---------|
| `write` | inline | `core/operators/write.py` |
| `edit` | mutation (staged diff) | `core/operators/edit.py` |
| `section` | sub-node session | `core/operators/section.py` |
| `collate` | structure (after-the-fact section) | `core/operators/collate.py` |
| `compress` | structure (AI-select range → collate) | `core/operators/compress.py` |
| `chat` | inline / session | `core/operators/chat.py` |
| `design` | session; command_tools for KB lookup | `core/operators/design.py` |
| `play` | session; GM voice; needs `pc.*` pinned | `rpg/operators/play.py` |
| `advance` | session; time/fronts | `rpg/operators/advance.py` |

## LLM pipeline (core modules)

- `context.py` — `crawl()` + `assemble_prompt()` (KB pins + fractal narrative spine)
- `llm_run.py` — `LlmRun` envelope: gather → pre-transform → generate → persist
- `prompt_transforms.py` — `@` on prompt strings (STORABLE / FLAT); `crawl_transforms.py` — graph transforms
- `workflow_runner.py` — multi-step scheduling (generate→auto_compress, summarize→remember→close)
- `hooks.py` — `post_inline` (auto-compress), `summarize_close` (remember)
- `command_tools.py` — inline KB tools mid-generation (`kb_get`, `kb_list_tags`, `kb_with_tag`); used by `design`
- `tools.py` — operator-as-LLM-tool registry; gated by `limited_to_datasets`
- `prompts.py` — layered prompt packs (default → dataset → project override)

**Workflow controls:** Skip = decline optional tail step (no rollback). Abort/Cancel = roll back dirty in-flight step. Discard = reject entire preview transaction. Do not stage between workflow steps.

## Key principles

- KB pins inherit root → cursor; `kb_unpin` cancels ancestors.
- Narrative crawl follows lineage spine only (siblings excluded; fractal summaries carry branch detail).
- HTML comments stripped (and sometimes ROT13-encoded) from player-facing context; visible to LLM-mode operators.
- Git unstaged = pending transaction; `git add -A` = stage; commit = checkpoint.
- Remember runs on summarize boundaries, not every inline generation.
- Command tools ≠ operators (no operator spawning from tools).

## KB store

- Lookup: project-local first, then datasets (later in list wins).
- Copy-on-write: mutating a dataset item materialises a local copy.
- `KnowledgeStore.clear_registry()` after `lens.toml` dataset changes in tests.

## Testing

```bash
poe check              # lint + types + unit + integration + test-ui + build-ui + e2e
poe test               # unit: lens/core/test, lens/cli/test, lens/server/test, lens/rpg/test
poe test-integration   # lens/core/test/integration only
poe test-e2e           # e2e/ (fake LLM, no real API key)
poe e2e-sandbox        # manual browser sandbox
```

- Integration tests must run with `-n 0` (sequential).
- `lens/conftest.py` disables git commit signing in cloud sessions.
- `setup_test_project()` + `FakeLLMServer` for throwaway projects; regression fixtures in `lens/testing/regression_fixtures.py`.
- `Storage(project_dir).checkpoint(msg)` stages+commits; only call when pending changes exist.
- Playwright: `playwright install chromium` once; `poe build-ui` before browser e2e.

## Frequently touched files

- `lens/core/knowledge.py` — KnowledgeStore, KnowledgeObject
- `lens/core/project.py` — ProjectSession, dataset path resolution
- `lens/core/storage.py` — git-backed transactional Storage
- `lens/core/dataset_extensions.py` — load dataset Python extensions
- `datasets/testing/lens_testing_ext/` — minimal extension fixture for unit tests
- `lens/core/test/integration/test_integration.py` — sequential happy-path tests
