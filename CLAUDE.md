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

## Definition of done

Always run `poe check` before considering a task complete. It runs lint, typecheck, and tests in sequence — all three must pass.

## Cloud environment (Claude Code on claude.ai)

Cloud sessions enforce signed git commits via a hook that calls an external
API (`/tmp/code-sign`).  `poe test` and `poe check` work correctly because
`lens/test/conftest.py` detects the environment at session start and injects
`GIT_CONFIG_COUNT` overrides that disable signing for all subprocess git calls
made during the pytest session.

**How to detect a cloud session**: `/home/claude/.ssh/commit_signing_key.pub`
exists.  Alternatively: `git config --global commit.gpgsign` returns `true`
with `gpg.ssh.program` pointing to `/tmp/code-sign`.

**What does NOT work in cloud sessions**:
- `lens/test/integration/` — excluded from `poe test` by design; requires a
  live LLM endpoint and a fully configured content repository.
- Any shell command that runs `git commit` outside of pytest (e.g. manual
  testing in a temp directory) will go through the signing hook, which works
  only when the session's API key is active.

## Architecture

Lens is a CLI tool for managing AI-assisted narrative creation. A **Lens project** is a Git repository with a `lens.toml`, `narrative/`, and `knowledge/` directory.

### Package layout

```
lens/
  cli/           # Typer CLI layer (argument parsing, error display)
    main.py      # Entry point + preflight callback
    commands/    # Non-AI commands (init, use, kb, pin, stats, rollback)
    operators/   # AI operator CLI adapters (write, edit, section, play)
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
    chain.py     # ChainSpec: deferred operator chaining within a transaction
    exceptions.py # Shared exception types
    commands/    # Core implementations for non-operator commands
    operators/   # Core implementations for AI operators (write, edit, section, play)
  test/          # unittest test suite
datasets/
  testing/       # Minimal dataset for integration tests
  dnd/           # D&D 2024 reference dataset (rules, spells, monsters, etc.)
    knowledge/   # KB objects: faction/, front/, loc/, lore/, npc/, pc/, rules/
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

**`play` operator** (`operators/play.py`): GM-voice narrative operator. Requires at least one KB object tagged `pc` to be pinned — the LLM knows who the player characters are and writes from the GM's perspective without narrating PC decisions. Dataset-gated: only available when the `dnd` dataset (or another RPG dataset) is selected in `lens.toml`.

**Context assembly** (`context.py`): `crawl()` collects `kb_pin`/`kb_unpin` from ancestor front matters (walking from root to cursor), resolves linked KB objects, then passes everything to `assemble_prompt()` which formats `[RELEVANT KNOWLEDGE]`, `[PREVIOUS EVENTS SUMMARY]`, `[CURRENT PASSAGE]`, and `[TASK]` blocks into `[system, user]` messages.

**KnowledgeStore** (`knowledge.py`): flat key-value store at `knowledge/{type}/{key}.md`. IDs are dot-separated lowercase (`person.amy`). Tags stored in `knowledge/tags.toml` with bidirectional index. The `+` suffix on an ID in a pin expands to linked objects (those sharing a dot-tag pointing to another KB object).

### LLM configuration

Configured in the content repo's `lens.toml`, not in this repo. Uses OpenAI-compatible API. First `[[llm]]` entry is the default; others require explicit `--llm <id>`. The `api_key_env` field names an environment variable holding the key (never stored in toml).

### Datasets

Read-only knowledge stores bundled with the Lens tool, declared in `lens.toml` under `[project] datasets = [...]`. Later entries shadow earlier ones; project-local items always win. Mutating a dataset object creates a project-local copy (copy-on-write).

- `datasets/testing/` — minimal test fixtures used by the test suite
- `datasets/dnd/` — D&D 2024 reference data: rules (`rules/dnd.md`, `rules/engagement.md`), NPC/PC/faction/front/loc/lore object templates. Populated via `tools/ddb-extract/` + `lens kb extract`.

### Tools

`tools/ddb-extract/` is a standalone TypeScript CLI (Playwright + CDP) that extracts D&D Beyond content into Lens KB-formatted Markdown files. Run `npm install` inside the directory, then invoke via `tsx src/cli.ts`. See `tools/ddb-extract/README.md`. The `ddb-extract-design.md` in `docs/` describes the original design (may be removed).
