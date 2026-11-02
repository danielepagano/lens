# CLAUDE.md

Agent-oriented grounding for this repository. It holds what you need before touching anything, and the invariants that **fail silently** when broken. Everything descriptive lives in the docs below. Read the one for the area you are about to change.

## Documentation map

| Before you… | Read |
|---|---|
| change anything architectural (stores, crawl, pending KB, mentions, live state, workflows) | [docs/design.md](docs/design.md) |
| touch `lens.toml`, LLM config, mounts, datasets, modules, validation | [docs/configuration.md](docs/configuration.md) |
| write or change a test, use the fake LLM, sandbox, prompt lab, bench | [docs/testing.md](docs/testing.md) |
| add or change a CLI command or operator flag | [lens/cli/README.md](lens/cli/README.md) |
| touch RPG play, `advance`, fronts, triggers, prep content | [docs/rpg-design.md](docs/rpg-design.md), [datasets/rpg/README.md](datasets/rpg/README.md) |
| touch a route, SSE, workflow actions | [lens/server/README.md](lens/server/README.md) |
| touch the Svelte UI | [lens/server/ui/CLAUDE.md](lens/server/ui/CLAUDE.md) (hard constraints) |
| touch datasets, extensions, sibling layout | [datasets/README.md](datasets/README.md) |
| touch companion chat | [datasets/companion/README.md](datasets/companion/README.md) |
| run quality checks against real models | [bench/README.md](bench/README.md), [bench/model-rating.md](bench/model-rating.md) |
| deploy | [deploy/README.md](deploy/README.md) |
| work *in a content project* (not this repo) | run `lens skill` there |

## Commands

`poetry` and `poe` are on PATH locally. In the cloud environment (`/home/claude/.ssh/commit_signing_key.pub` exists) use `/root/.local/share/uv/tools/poetry/bin/poetry run poe …`.

```bash
poe check              # lint + types + unit + integration + UI unit + build-ui + e2e — the definition of done
poe lint               # ruff + eslint + svelte-check + pyright
poe test               # pytest unit tests
poe test-integration   # core integration tests
poe test-e2e           # full stack (Playwright tests skip without Chromium + built UI)
poe test-ui            # Vitest
poe build-ui           # vite build → lens/server/static/ (browser e2e runs against this)
poe prompt-lab --scenario bench/scenarios/<s>.md -o play   # measure an assembled prompt
poe lens <command>     # run the CLI from this checkout
poetry run python -m pytest path/to/test.py -k name        # one test
```

## Definition of done

`poe check` passes. All of it: lint, types, unit, integration, UI unit, UI build, e2e.

## Editing prompts and KB content

`lens/prompts/default.toml`, `datasets/*/knowledge/design/*`, `datasets/*/knowledge/rules/*`, and every `_template.md` are **LLM prompts**, not documentation. The diff is not the artifact. The *assembled context* is, and no test asserts on it. Measure with `poe prompt-lab` before and after ([docs/testing.md](docs/testing.md#prompt-lab-poe-prompt-lab)):

```bash
poe prompt-lab --scenario bench/scenarios/play_dnd_rules_split.md -o play --out /tmp/before
#  …edit…
poe prompt-lab --scenario bench/scenarios/play_dnd_rules_split.md -o play --baseline /tmp/before
```

It owns no content. If a sweep needs material that does not exist, **add a bench scenario**, never a fixture inside the tool.

- **Never assemble in-process right after writing KB objects.** `KnowledgeStore` caches its tag index per project, so a fresh tag can read stale and a `+` expansion silently resolves to nothing. Shell out to the CLI, or verify anything surprising through it.
- **Check the play side after any design-side edit.** They share `rules.*` objects. `rules.<type>` companions are resolved by `crawl()` for every operator, so a booklet edited for `design` lands in every beat that has an object of that type in scope.
- **Budget asymmetry.** Guidance in a design module is paid once per design session. Guidance in a `rules.*` booklet or `rules.rpg` is paid on *every* beat that has one of its objects in scope.
- **Whole-system guidance goes in the operator prompt; one task's guidance goes in its module.** If the same text has to go into two modules, it belongs in the prompt, or it is a module that does not exist yet (#152).
- **A KB object is already the artifact.** `design.*` modules make their object *actionable* (a limit, an access rule, a break condition `play` can check) by improving the object's guidance and its `_template` together.
- **Content conventions are machinery.** The first-three-lines self-description, type-as-tag discovery, `rules.<type>` companions and trigger front matter are described in [docs/rpg-design.md](docs/rpg-design.md) and [docs/configuration.md](docs/configuration.md). Breaking them fails silently.

## Layout

```
lens/
  cli/        Typer adapters: commands/ (non-AI), operators/ (AI), offers.py (trigger offer prompt)
  core/       all business logic (no Typer): operators/, commands/, context.py (crawl + assembly),
              knowledge.py (KnowledgeStore), kb_pending.py + kb_op_tools.py (proposed KB writes),
              triggers.py, storage.py (git transactions), annotations.py, narrative.py, llm*.py
  rpg/        bundled rpg operators: play, advance, test_play
  server/     FastAPI adapter + Svelte UI (lens/server/ui/)
  testing/    fake LLM, setup_test_project, sandbox, regression fixtures, prompt lab
  skill/      `lens skill` text (guidance.md emitted, pointer.md committed into content repos)
datasets/     testing/, rpg/, companion/ (others resolve from a sibling repo; see datasets/README.md)
bench/        real-model quality runs;  e2e/  full-stack tests;  docs/  design docs
```

Every command has a `cli/` adapter and a `core/` implementation. **Business logic goes in `core/`.** The server imports only from `core/`, never from `cli/`. Core is synchronous and raises exceptions; it never calls `sys.exit()` or `print()`.

## Invariants that fail silently

Each is one line here, with the full story in the linked doc or the module docstring. Read that before changing the area.

- **Surfaces have parity.** The CLI, the server routes and the UI command bar accept the same command lines with the same meaning. When one lacks something another has, that is a bug: fix it, don't route around it.
- **The cursor is derived, never stored.** `find_cursor()` descends tail annotations. Anything appended at a node's tail must be skipped by the tail scan or be outside the annotation grammar: markdown comments with a hyphenated token (`[kb-op …]`, `[llm-trace …]`), `[mention:/include:]` lines, HTML comments. Otherwise the cursor silently jumps out of an open session. (`annotations.py`)
- **Git's unstaged area is the one pending transaction.** Every write goes through `Storage` with an owner. `StorageMode.DIRECT` is for direct user edits only, never for generated content. ([docs/design.md](docs/design.md), "Git-backed storage", "Direct user edits")
- **Proposed KB writes are an overlay, not writes.** `design`/`advance` persist `[kb-op …]: #` blocks inside the operator's block. `fold()` serves them as a pending layer at the store's *read primitives*. **Writers must call the `_base` methods.** Materialization re-reads the node at `--end`. ([docs/design.md](docs/design.md), "Pending KB layer"; `kb_pending.py`)
- **Anything users update mid-session renders at the tail.** `state`-tagged objects go to `[LIVE STATE]`, and open triggers go to `[HELD BACK]` for play and advance. Both sit just before `[TASK]`. In the prefix they would invalidate the cache on every change. New context sources must set component metadata rich enough for `lens explain` to attribute them. ([docs/design.md](docs/design.md), "Live state")
- **Triggers are done by node name.** A `<slug>-tr` node existing in the narrative is the only state, and the `-tr` suffix is reserved. ([docs/rpg-design.md](docs/rpg-design.md), "Held-back parts: triggers"; `triggers.py`)
- **The crawl never shows where an object came from.** `KbSource` is for browsing surfaces only. During generation a KB object is world truth.
- **A type is a tag; an object's first three lines are its description.** `design` discovers modules and `load_module` builds its catalog this way, so a stale tag or a badly shaped opening hides an object rather than mislabelling it.
- **"What would run here" and "is a session open" are different questions.** Use `detect_operator_name()` for the first and `detect_open_session_operator()` for the second; the second is only for `--end` affordances. (`core/operator_detect.py`)
- **Reasoning is replayed within a generation.** Tool rounds carry `reasoning_details` back verbatim, because a tool round is the same reply resumed. Providers name the field differently, so `_reasoning_from_delta` takes the first hit only. (`llm.py`)
- **Nothing descriptive is committed into a content repo.** `lens skill --install` writes a pointer only, and the guidance is generated by the installed Lens. ([lens/cli/README.md](lens/cli/README.md#agent-onboarding-lens-skill))

## Testing notes

The full map is in [docs/testing.md](docs/testing.md). The facts you need first:

- `FakeLLMServer` streams Lorem Ipsum followed by `[input:<N>]`, the total input chars, so tests can assert context assembly. It can also emit tool calls on cue (`EMIT_KB_OP`).
- `setup_test_project(dir, llm.base_url, datasets=[…])` builds a real throwaway project (git repo, `lens.toml`, KB, narrative).
- A browser e2e test that changes the cursor gets its own project and server (see `e2e/tests/test_trigger_offer_browser.py`), not the shared session fixture.
- In the cloud, `lens/conftest.py` disables commit signing for every git call made during a pytest session.
