# Lens datasets

A **dataset** is a read-only bundle of **knowledge** (and optional design templates) that Lens merges into your projects. Datasets let you share a game system, setting, or play mode without copying hundreds of markdown files into every campaign repo.

This repository ships two bundled datasets:

| Name | Folder | Guide |
|------|--------|--------|
| `rpg` | `datasets/rpg/` | [rpg/README.md](rpg/README.md) |
| `lens-dnd` | `datasets/lens-dnd/` | [lens-dnd/README.md](lens-dnd/README.md) |
| `companion` | `datasets/companion/` | [companion/README.md](companion/README.md) |

Other datasets (for example a private D&D reference tree) are **not** part of Lens — you create or clone them separately and Lens discovers them by **directory name**.

## What goes in a dataset

Minimum layout:

```
my-ruleset/
  lens.toml          # must contain [dataset] — marks this tree as a dataset, not a project
  knowledge/
    tags.toml        # optional tag index
    rules/
      system.md      # example KB object id: rules.system
    pc/_template.md
  prompts/prompts.toml # optional: operator prompt text this dataset ships
  skill/skill.md       # optional: conventions an agent must not break
```

Typical contents:

- **`knowledge/{type}/{key}.md`** — KB objects (rules, templates, meta pins, design interview modules under `knowledge/design/`, …)
- **`knowledge/tags.toml`** — bidirectional tag index (optional but usual)
- **`lens.toml`** — `[dataset]` marker, optional `extension`, optional `[[dataset.modules]]`
- **`prompts/prompts.toml`** — operator prompt overrides (see [configuration.md](../docs/configuration.md))
- **`skill/skill.md`** — this dataset's conventions, emitted by `lens skill` in any project that selects it

### Agent conventions (`skill/skill.md`)

A dataset is the thing that knows its own conventions, and the ones that matter
are the ones that break *silently* — a naming rule an operator keys off, a tag
that must not be applied, a budget that is paid on every beat. Write those here
and `lens skill` emits them to any agent working in a project that selects this
dataset, after the bundled invariants and the project's live shape. Ordinary
reference material belongs in the README instead: this text is read on every
agent session, so it pays the same length discipline a rules booklet does.

The same path in a *project* holds house rules, and in a dataset checkout it is
the layer being edited — `lens skill --sources` says which is which.

### Templates (`{type}/_template.md`)

A `_template.md` seeds `lens kb add <id> -t` (and any other `use_template=True` creation path — the KB UI's "use template" checkbox, dataset extensions) with default content for every new object of that type. It can also declare a default **tag set** in its own front matter, applied once at creation:

```
[
    kb-details: true
    tags: state
]: #

Describe the place: notable features, mood, who's usually here.
```

The `tags:` key is consumed by creation — it is stripped from the new object's body and applied via the normal tag index instead, so tagging stays in `tags.toml` rather than duplicated inline. Removing a tag afterward is not re-applied; existing objects are never migrated when a template's `tags:` declaration changes. See [Template default tags](../docs/configuration.md#template-default-tags) for the full contract, including how this interacts with the `design` operator's `kb` fences.

Datasets do **not** have `narrative/` or `[project]`. Stories always live in **your** project repo; datasets only supply shared reference material.

## How projects use datasets

In **your** project’s `lens.toml`:

```toml
[project]
narrative = "my-campaign"
datasets  = ["rpg", "my-ruleset"]
```

Resolution order for each name (first match wins):

1. **Bundled** — `lens/datasets/<name>/` inside the Lens install
2. **Sibling folder** — `<parent-of-lens-repo>/<name>/` (see layout below)
3. **Explicit path** — `[dataset_paths]` in the project’s `lens.local.toml` (gitignored local file)

Later names in the `datasets` list **shadow** earlier ones for the same KB id. Anything you edit in the project is stored under `knowledge/` in **your** repo (copy-on-write); dataset files are never modified in place.

To see which store an object actually resolves from, read the `SOURCE=` field `lens kb get` prints for it — see [Where an object comes from](../lens/cli/README.md#where-an-object-comes-from).

## Sibling layout (recommended for your own datasets)

If you develop Lens from a clone and keep private datasets next to it:

```
~/dev/
  lens/                 # this repository
  my-ruleset/           # your private dataset repo (NOT shipped with Lens)
  my-campaign/          # your Lens project (git repo + lens.toml + narrative/)
```

The folder name (`my-ruleset`, `acme-5e`, …) must match the string in `datasets = [...]`. With that layout, a project can use:

```toml
datasets = ["rpg", "my-ruleset"]
```

without any path configuration, as long as `~/dev/my-ruleset/` exists and contains `lens.toml` with `[dataset]`.

## Explicit paths (`lens.local.toml`)

When a dataset lives elsewhere, add a **project-local** file (not committed):

```toml
# my-campaign/lens.local.toml
[dataset_paths]
my-ruleset = "/Users/you/dev/my-ruleset"
shared-homebrew = "../shared-homebrew"
```

Relative paths are resolved from the project root. This overrides bundled/sibling lookup for that name only.

## Working on a dataset with the Lens CLI

`cd` into the dataset directory and run Lens like a lightweight KB workspace:

```bash
cd ~/dev/my-ruleset
lens stats
lens kb add rules.system -t
lens kb get rules.system
lens kb tag rules.system core
lens check
```

Dataset mode is detected from `[dataset]` in `lens.toml`. Allowed commands include **`kb`**, **`stats`**, **`prompt`**, **`check`**, **`commit`**, **`rollback`**, **`serve`**, and **`dev`**. Narrative operators (`write`, `play`, `section`, …) and **`lens init` / `lens use`** are not available — there is no story tree in a dataset.

To try dataset KB against a real LLM from the dataset folder, configure `[[llm]]` in that directory’s `lens.toml` the same way as a project (unusual but supported), or validate objects from a **project** that lists the dataset in `datasets`.

## Dataset extensions (optional Python)

Most datasets are KB + templates only. When a dataset also needs CLI commands or LLM tools (e.g. `balance_encounter` for D&D), colocate a Python package in the dataset directory and declare it in `lens.toml`:

```toml
[dataset]
extension = "my_dataset_pkg"   # import from dataset root (sys.path)
# or
extension = "my_dataset_pkg:register"   # call register() after import
```

Layout example (private `lens-dnd` repo):

```
lens-dnd/
  lens.toml              # [dataset] extension = "lens_dnd"
  knowledge/             # KB (required for KB merge)
  prompts/prompts.toml   # optional tool/operator prompt snippets
  lens_dnd/              # Python package
    __init__.py          # register() — registers CLI + command tools
    cli.py
    balance_encounter.py
```

When a project lists the dataset in `[project] datasets`, Lens resolves the dataset path (bundled, sibling, or `lens.local.toml`), loads the extension on CLI/server startup, and merges `prompts/prompts.toml` into the prompt store. No pip install — the dataset folder is added to `sys.path`.

On **Fly deploy**, `lens deploy push` already copies external dataset trees into the image at `datasets/<name>/`; extension code in that tree is included automatically. See [deploy/README.md](../deploy/README.md).

Bundled **`rpg`** operators (`play`, `advance`) remain in the Lens package (`lens.rpg`); they are not loaded via `[dataset] extension`.

## Creating a new dataset from scratch

1. Create a directory and a git repo if you want version control.
2. Add `lens.toml`:

   ```toml
   [dataset]
   # extension = "my_pkg"   # optional, if the dataset ships Python features
   ```

3. Add `knowledge/` and objects (copy structure from `datasets/rpg` or `datasets/companion` as a model).
4. Place the folder as `../<name>/` next to your Lens clone **or** register `[dataset_paths]` in projects that use it.
5. In each consumer project: `datasets = ["<name>"]` (and any dependencies, e.g. `rpg` before a rules override dataset).

Document your dataset in its own `README.md` (enablement TOML, bootstrap steps, pins). Link it from your projects’ notes or team docs.

## Related

- [Project configuration](../docs/configuration.md) — `[project].datasets`, shadowing, `lens check`
- [Main README — datasets](../README.md#datasets-optional-bundles)
- [Design — datasets](../docs/design.md) — product role of datasets in context assembly
- D&D reference KB and `lens dnd` / `balance_encounter` — private `lens-dnd` dataset (not shipped with Lens); see that repo’s README
