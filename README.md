# Lens

[![check](https://github.com/danielepagano/lens/actions/workflows/check.yml/badge.svg)](https://github.com/danielepagano/lens/actions/workflows/check.yml)

A system for composable AI-assisted interactive fiction.

## Overview

Lens is for **long-running, grounded creative work** with language models — fiction, tabletop play, companion chat, and world-building — where “dump the whole repo into context” stops working.

You keep **your** story and lore in a normal Git repo: Markdown narrative nodes, a typed **knowledge store** (characters, places, rules), and `lens.toml` for backends and behaviour. Lens gives you:

- A **CLI** for operators (`write`, `edit`, `section`, `play`, `design`, …), KB management, pins, and Git-backed preview/commit
- A **web UI** on the same API — edit the tree, run operators, inspect pending changes without git jargon

What makes it different:

- **Operators and workflows** — `write`, `edit`, `section`, `play`, `design`, and multi-step tails (auto-compress, remember) with explicit skip/abort semantics
- **Pins and crawl** — declare what is “in frame” per node; KB and narrative slices assemble at the right resolution
- **Fractal tree** — parent summaries, child detail, so campaigns stay coherent
- **Transactional edits** — preview unstaged work, save, checkpoint (Git underneath, friendly UI vocabulary)
- **Composable datasets** — RPG rules, companion chat, or your own bundles plug in without forking the tool

For the product model, see **[Design](docs/design.md)**. For how this repo is organized for coding agents, see **[CLAUDE.md](CLAUDE.md)**.

## Install Lens (the tool)

Requires **Python 3.12+** and **[Poetry](https://python-poetry.org/docs/#installation)** on your machine.

From a clone of this repository:

```bash
cd /path/to/lens && poetry install
```

Use an in-project venv (`poetry config virtualenvs.in-project true`, then add `.../lens/.venv/bin` to your `PATH`), or run `poetry -C /path/to/lens run lens <command>`.

---

## Getting started

### What is a Lens project?

A **Lens project** is **your** Git repository — campaign, novel, or experiment — plus Lens metadata:

| Path | Your content |
|------|----------------|
| `lens.toml` | Configuration (LLM, datasets, optional media mount) — see **[Configuration](docs/configuration.md)** |
| `knowledge/` | Lore sheets (`person.hero`, `place.inn`, …) and `tags.toml` |
| `narrative/` | Story trees (`<slug>/_node.md` and child nodes) |

`lens init` must be run **inside an existing Git repo** (create the repo first with `git init`). Lens does not replace Git; it structures files and orchestrates AI calls on top.

### Quick paths

| Goal | Next step |
|------|-----------|
| Write fiction | Follow steps 1–3 below |
| Use companion chat | [Companion dataset guide](datasets/companion/README.md); `datasets = ["companion"]` in `lens.toml` |
| Play tabletop RPGs | [RPG dataset guide](datasets/rpg/README.md); `datasets = ["rpg"]` in `lens.toml` |
| Play D&D | [D&D dataset guide](datasets/lens-dnd/README.md); `datasets = ["rpg", "lens-dnd"]` in `lens.toml` |

**Starter `lens.toml` fragment** (add your API details):

```toml
[project]
datasets = ["companion"]   # or ["rpg"] for tabletop play

[[llm]]
base_url = "https://api.openai.com/v1"
model = "gpt-4o"
api_key_env = "OPENAI_API_KEY"
```

### 1. Set up a project

```bash
cd ~/my-story          # your git repo
git init               # if new
lens init              # lens.toml, knowledge/, narrative/
```

Add at least one **`[[llm]]`** block in `lens.toml` (API URL, model, `api_key_env` pointing at your key). Validate with:

```bash
lens check
```

Full reference: **[Configuration](docs/configuration.md)** (`[project]`, datasets, compression, image/speech, params).

```bash
lens use my-campaign   # active narrative (creates narrative/my-campaign/ if needed)
```

For companion chat bootstrap from the CLI:

```bash
lens use my-chat --companion companion.mara --human human.adam
```

### 2. Use the CLI

**Knowledge** — facts the model can use:

```bash
lens kb add person.hero "A wary elven ranger who trusts few people."
lens kb get person.hero
```

**Pins** — what counts as “in frame” for AI calls from a node (inherited down the tree):

```bash
lens pin kb add person.hero              # pin at the cursor node
lens write "The ranger studies the map." # only pinned KB + narrative context go to the LLM
```

You can also pin inline in the prompt: `lens write "describe @person.hero arriving at the inn"`.

**Write** at the cursor:

```bash
lens write "Open on a storm over the harbor."
lens stats
```

Rollback preview work with `lens rollback`; stage with `lens commit`; push a checkpoint with `lens checkpoint`.

Command reference (operators, sections, play, media, pins, prompt syntax): **[CLI reference](lens/cli/README.md)**.

### 3. Use the web UI

From the **same project directory** (where `lens.toml` lives):

```bash
lens serve    # build UI + API at http://127.0.0.1:8000 — open that URL in a browser
lens dev      # UI dev mode with HMR at http://localhost:5173 (for hacking on lens/server/ui)
```

The UI uses the project on disk (narrative tree, KB browser, operators, pending-change preview). API details: **[Web UI & server](lens/server/README.md)**.

**Cloud deploy** (Fly.io, Docker, Caddy auth, persistent volume): **[Deployment](deploy/README.md)**. Configure `lens.toml` and API keys locally first; `lens deploy init` / `lens deploy push` read them from your environment.

### Datasets (optional bundles)

Declare dataset **names** in `lens.toml` under `[project] datasets = [...]`. Lens merges each dataset’s `knowledge/` into your project (templates, rules, meta pins) without copying files into your repo. Later names in the list shadow earlier ones; edits you make in the project stay local (copy-on-write).

**Shipped with this repo:** `rpg`, `companion`, `lens-dnd` — see [datasets/README.md](datasets/README.md) for what a dataset is, how to author one, and how discovery works.

| Bundled | Guide |
|---------|--------|
| `companion` | [Companion](datasets/companion/README.md) — dyadic chat, memory, remember |
| `rpg` | [RPG](datasets/rpg/README.md) — `play`, `advance`; default [system stub](datasets/rpg/knowledge/rules/system.md) (replace via another dataset) |
| `lens-dnd` | [D&D](datasets/lens-dnd/README.md) — 5.5e SRD rules, stat blocks, spells, encounter design; requires `rpg` |

**Your own datasets** (private repos, homebrew rules) live **outside** Lens — typically as a **sibling folder** next to your `lens` clone (e.g. `../my-ruleset/`, `../lens-dnd/` for D&D) or via `[dataset_paths]` in `lens.local.toml`. Folder name must match the string in `datasets`. Datasets may declare `[dataset] extension` to ship Python (CLI commands, LLM tools) alongside KB — see [datasets/README.md](datasets/README.md). You can run `lens kb` / `lens stats` from inside the dataset directory while editing it.

---

## Documentation

**User and configuration**

- **[Datasets](datasets/README.md)** — bundled vs external datasets, sibling layout, authoring
- **[Configuration](docs/configuration.md)** — `lens.toml`, backends, mounts, compression, env vars, `lens check`
- **[Deployment](deploy/README.md)** — Fly.io hosting, secrets, local Caddy
- **[CLI reference](lens/cli/README.md)** — commands and operators

**Architecture and agents**

- **[Design](docs/design.md)** — architecture and product model
- **[CLAUDE.md](CLAUDE.md)** — documentation map and conventions for coding agents
- **[Testing](docs/testing.md)** — pytest layout, fake LLM, e2e sandbox, bench

## Hacking on Lens

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for setup, `poe check`, and PR expectations.
