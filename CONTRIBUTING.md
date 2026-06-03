# Contributing to Lens

Thank you for your interest in Lens. This repository is the Lens **tool**; creative projects live in separate Git repos with their own `lens.toml`.

## Development setup

Requirements: **Python 3.12+**, **[Poetry](https://python-poetry.org/docs/#installation)**, **Node.js** (for the web UI).

```bash
git clone <your-fork-url> lens && cd lens
poetry install
cd lens/server/ui && npm install
```

Optional (browser e2e tests):

```bash
playwright install chromium
```

Run the full quality gate (same as CI):

```bash
poe check
```

Individual tasks: `poe lint`, `poe test`, `poe test-integration`, `poe test-ui`, `poe build-ui`, `poe test-e2e`. See [docs/testing.md](docs/testing.md) for fake LLM, sandbox, and bench workflows.

## Planned work

Open **[GitHub Issues](https://github.com/danielepagano/lens/issues)** (`backlog`, `release` labels). Broader design threads belong in **[Discussions](https://github.com/danielepagano/lens/discussions)**.

## Pull requests

1. Branch from `main`.
2. Keep changes focused; put business logic in `lens/core/`, not in CLI or server routes.
3. Run `poe check` before opening a PR.
4. Update docs when you change user-visible behavior (README, CLI reference, dataset guides).

## Architecture notes for agents and maintainers

- **[CLAUDE.md](CLAUDE.md)** — documentation map and repo conventions for coding agents.
- **[docs/design.md](docs/design.md)** — product model, operators, workflows.
- **[lens/server/ui/CLAUDE.md](lens/server/ui/CLAUDE.md)** — frontend constraints (services/stores split, component size).

## Cloud / signed commits

Some hosted dev environments enforce signed Git commits. Local `poe test` / `poe check` disable signing for subprocess git calls during pytest via `lens/conftest.py`. You do not need special setup for normal local development.
