# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
poetry install

# Run all checks (lint + typecheck + tests)
poe check

# Individual checks
poe lint       # ruff (auto-fix)
poe pyright    # type checking
poe test       # unittest discover

# Run a single test module
python -m unittest lens.test.test_annotations

# Run a single test method
python -m unittest lens.test.test_annotations.TestAnnotations.test_method_name

# Run the CLI locally (suppresses pysbd SyntaxWarning)
poe lens <command>
```

## Architecture

Lens is a CLI tool for managing AI-assisted narrative creation. A **Lens project** is a Git repository with a `lens.toml`, `narrative/`, and `knowledge/` directory.

### Package layout

```
lens/
  cli/           # Typer CLI layer (argument parsing, error display)
    main.py      # Entry point + preflight callback
    commands/    # Non-AI commands (init, use, kb, pin, stats, rollback)
    operators/   # AI operator CLI adapters (write, edit, section)
  core/          # Business logic (no Typer dependency)
    project.py   # Git/project root discovery, active narrative resolution
    narrative.py # NarrativeNode tree model, NodeSegment, parse_segments()
    annotations.py # Markdown comment-style annotation parsing
    operator.py  # Operator base class + ContextAwareOperator (LLM flow)
    context.py   # crawl() + assemble_prompt() for LLM context assembly
    knowledge.py # KnowledgeStore + KnowledgeObject (filesystem KB)
    pinning.py   # Front matter kb_pin/kb_unpin manipulation
    storage.py   # Storage: git-backed transactional file writes
    address.py   # NarrativeAddress: typed path + line + operator location
    llm.py       # OpenAI-compatible LLM client (streaming)
    commands/    # Core implementations for non-operator commands
    operators/   # Core implementations for AI operators
  test/          # unittest test suite
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

**ContextAwareOperator** (`operator.py`): abstract base for LLM operators. Provides three operating modes:
- *Inline* (`write`): open tag + streamed content + close tag appended to cursor node
- *Sub-node* (`section`): creates a child node, appends open tag to parent
- *Mutation* (`edit`): wraps a line range in staged claim tags; proposes replacement as unstaged diff

**Context assembly** (`context.py`): `crawl()` collects `kb_pin`/`kb_unpin` from ancestor front matters (walking from root to cursor), resolves linked KB objects, then passes everything to `assemble_prompt()` which formats `[RELEVANT KNOWLEDGE]`, `[PREVIOUS EVENTS SUMMARY]`, `[CURRENT PASSAGE]`, and `[TASK]` blocks into `[system, user]` messages.

**KnowledgeStore** (`knowledge.py`): flat key-value store at `knowledge/{type}/{key}.md`. IDs are dot-separated lowercase (`person.amy`). Tags stored in `knowledge/tags.toml` with bidirectional index. The `!` suffix on an ID in a pin expands to linked objects (those sharing a dot-tag pointing to another KB object).

### LLM configuration

Configured in the content repo's `lens.toml`, not in this repo. Uses OpenAI-compatible API. First `[[llm]]` entry is the default; others require explicit `--llm <id>`. The `api_key_env` field names an environment variable holding the key (never stored in toml).
