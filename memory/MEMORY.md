# Lens Project Memory

## Key Architecture
- CLI layer: `lens/cli/` (Typer), Business logic: `lens/core/` (pure Python)
- Every command has parallel `cli/` adapter + `core/` implementation
- `poe check` = lint (ruff) + typecheck (pyright) + tests (unittest) — must all pass

## Implemented Features

### KB Datasets (done)
- Datasets live at `datasets/<name>/` in the Lens repo root (shipped with the tool)
- Projects activate datasets via `lens.toml`: `[project] datasets = ["testing"]`
- `KnowledgeStore` loads dataset stores from lens.toml via `_build_dataset_stores()`
- Lookup order: project-local first, then datasets (later in list wins)
- Copy-on-write: mutating a dataset item (add_tags, remove_tags) materialises a local copy
- `store_object(id, None)` treats dataset items as "existing" (no-op)
- `delete_object` is a no-op for dataset-only items
- `copy_object` works when source is in a dataset (writes content directly)
- `rename_object` raises ValueError if source is dataset-only
- Registry (`KnowledgeStore.for_project`) picks up datasets from lens.toml on first access
- Call `KnowledgeStore.clear_registry()` to force reload after lens.toml changes

## File Locations
- `lens/core/knowledge.py` — KnowledgeStore, KnowledgeObject, parse_id
- `lens/core/project.py` — ProjectSession, find_git_root, require_lens_context
- `lens/core/context.py` — crawl(), assemble_prompt()
- `lens/core/storage.py` — git-backed transactional Storage
- `lens/core/test/integration/test_integration.py` — sequential happy-path integration tests
- `datasets/testing/knowledge/` — testing dataset with person.hero + place.dungeon

## Testing Patterns
- Integration tests: sequential, each depends on previous state, prefixed test_NN_
- KnowledgeStore.clear_registry() needed between dataset config changes and store access
- `Storage(project_dir).checkpoint(msg)` stages+commits; only call when pending changes exist
