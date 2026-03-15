# Lens Project Memory

## Key Architecture
- CLI layer: `lens/cli/` (Typer), Business logic: `lens/core/` (pure Python), D&D-specific: `lens/dnd/`
- Every command has parallel `cli/` adapter + `core/` implementation
- `poe check` = lint (ruff) + typecheck (pyright) + unit tests + integration tests — all four must pass

## Package Layout
- `lens/cli/commands/` — non-AI commands: init, use, kb, pin, stats, rollback, commit, checkpoint, dnd
- `lens/cli/operators/` — AI operator CLI adapters: write, edit, section, play, design
- `lens/core/operators/` — core AI operators: write, edit, section, design
- `lens/dnd/operators/` — D&D operators: play (dataset-gated)
- `lens/dnd/commands/` — D&D commands: balance_encounter
- Tests: `lens/core/test/`, `lens/cli/test/`, `lens/dnd/test/`; integration: `lens/core/test/integration/`

## Implemented Operators
- `write` — inline narrative generation (cursor node)
- `edit` — LLM rewrite of a line range (mutation mode, staged diff)
- `section` — start/end section at cursor (`section <id>`, `section --end`); `collate` for after-the-fact range
- `design` — **implemented** — Session Zero planning operator; uses command_tools (inline KB lookup mid-generation); lives in `lens/core/operators/design.py`
- `play` — **implemented** — GM-voice narrative; requires `pc`-tagged KB object pinned; dataset-gated (dnd); lives in `lens/dnd/operators/play.py`

Backlog operators (designed, not yet coded): `lore`, `converse`, `encounter`, `advance`.

## Core Architecture — Key Modules
- `operator.py` — Operator base class; includes tool use loop and operator chaining
- `tools.py` — `OperatorToolDef` + registry; operators self-register as LLM-callable tools; gated by `limited_to_datasets`
- `command_tools.py` — Lightweight inline KB lookup tools (kb_get, kb_list_tags, kb_with_tag) callable mid-LLM-generation without exiting the loop; used by `design` operator
- `chain.py` — `ChainSpec`: after operator completes, chains to another within same storage transaction
- `exceptions.py` — shared exception types
- `context.py` — `crawl()` + `assemble_prompt()` — KB pin resolution + prompt assembly

## Key Architectural Principles
- KB pins are hierarchical — ancestor pins flow to all descendants via `crawl()`
- `dm:` sections stripped from player-facing context assembly, visible to GM-mode operators
- Git unstaged area = pending transaction; `git add -A` = commit transaction

## KB Store
- Lookup order: project-local first, then datasets (later in list wins)
- Copy-on-write: mutating a dataset item materialises a local copy
- `KnowledgeStore.clear_registry()` to force reload after lens.toml changes

## File Locations
- `lens/core/knowledge.py` — KnowledgeStore, KnowledgeObject, parse_id
- `lens/core/project.py` — ProjectSession, find_git_root, require_lens_context
- `lens/core/context.py` — crawl(), assemble_prompt()
- `lens/core/storage.py` — git-backed transactional Storage
- `lens/core/test/integration/test_integration.py` — sequential happy-path integration tests
- `datasets/testing/knowledge/` — testing dataset with person.hero + place.dungeon
- `lens/conftest.py` — pytest config at lens package root; disables git commit signing in cloud

## Testing Patterns
- Unit tests: `pytest lens/core/test lens/cli/test lens/dnd/test -n auto --ignore=lens/core/test/integration`
- Integration tests: `poe test-integration`; also included in `poe check`
- KnowledgeStore.clear_registry() needed between dataset config changes and store access
- `Storage(project_dir).checkpoint(msg)` stages+commits; only call when pending changes exist
