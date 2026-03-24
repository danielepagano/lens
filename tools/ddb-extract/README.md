# ddb-extract

Extracts D&D Beyond content into Lens KB-formatted Markdown files. Covers spells, monsters, magic items, equipment, plus class/species features. Output files are consumed directly by `lens kb extract`.

No LLM involved — this is deterministic DOM scraping: list page → detail page → structured data → `\`\`\`kb\`\`\`` block.

---

## Prerequisites

- **Node.js** 18+
- **Google Chrome** (not Chromium) running with the remote debug port open
- A **D&D Beyond account** with the content you want to extract (subscriptions apply)

Start Chrome with the debug port (add this alias to your shell profile for convenience):

```bash
# macOS — requires a non-default user-data-dir (Chrome blocks CDP on its default profile).
# First-time setup: mkdir -p ~/chrome-ddb-profile, launch, sign in to D&D Beyond once.
# After that, credentials persist and you just run the alias.
alias chrome-debug='/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-ddb-profile" \
  --no-first-run &'

# Linux
alias chrome-debug='google-chrome --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-ddb-profile" --no-first-run &'
```

> **macOS note:** Chrome refuses `--remote-debugging-port` on its default data directory
> (`~/Library/Application Support/Google/Chrome`). You must pass `--user-data-dir` pointing
> elsewhere. The alias above uses `~/chrome-ddb-profile` — create it once with
> `mkdir -p ~/chrome-ddb-profile` and sign in to D&D Beyond; the session persists across runs.

Chrome must already be signed in to D&D Beyond before running any `ddb` command.

---

## Setup

```bash
cd tools/ddb-extract
npm install
```

All commands are run via `tsx` (no build step required):

```bash
./node_modules/.bin/tsx src/cli.ts --help
```

For convenience, alias it in your shell:

```bash
alias ddb='tsx /path/to/lens/tools/ddb-extract/src/cli.ts'
```

---

## Commands

### `ddb check`

Connects to Chrome via CDP and confirms the D&D Beyond session is active.

```bash
ddb check
ddb check --cdp-url http://localhost:9222   # default
```

Run this first to verify everything is wired up before a long extraction run.

---

### `ddb parse`

Loads a URL in the connected Chrome tab, runs a parser (spell, equipment, item, monster, or list), and pretty-prints the result as JSON. Useful for testing parsers against live pages.

```bash
# Spell page with spell parser (should succeed)
ddb parse --parser spell --url "https://www.dndbeyond.com/spells/2618909-fly"

# Same spell URL with equipment parser (should fail — wrong page shape)
ddb parse --parser equipment --url "https://www.dndbeyond.com/spells/2618909-fly"
```

---

### `ddb sources`

Lists all known sources from `config/sources.json`.

```bash
ddb sources
```

---

### `ddb discover-all`

Scrapes the source filter options from all four list pages (`/spells`, `/monsters`, `/magic-items`, `/equipment`) and rebuilds `config/sources.json` with every source and its filter ID. Existing hand-written entries are preserved and merged (matched by `filterId`).

```bash
ddb discover-all
ddb discover-all --verbose   # show per-page counts and selector hits
```

Run this once after first setup, and again whenever new books are released. If nothing is found, see the selector notes in `src/parsers/source-filter.ts`.

---

### `ddb discover <slug>`

Navigates to a source page on D&D Beyond to automatically detect and save its numeric filter ID for a single source. Run this for any source that shows `no filter ID` after `discover-all`.

```bash
ddb discover ghpg
```

If auto-detection fails (D&D Beyond may require interacting with the filter UI), set the ID manually in `config/sources.json`.

---

### `ddb extract`

Extracts content and writes one Markdown file per type.

```bash
# Extract spells from PHB 2024
ddb extract --type spells --source phb-2024 --out ./output

# Extract monsters from Monster Manual 2025
ddb extract --type monsters --source mm-2025 --out ./output

# Extract all list-based types for a source (one file per type)
ddb extract --type all --source phb-2024 --out ./output

# Extract class features from one class URL
ddb extract --type class-features --out ./output --url "https://www.dndbeyond.com/classes/2190885-druid"

# Extract species features for one index group label
ddb extract --type species-features --out ./output --group "Player’s Handbook"
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--type <type\|all>` | required | `spells`, `monsters`, `items`, `equipment`, `class-features`, `species-features`, or `all` |
| `--source <slug>` | — | Required for `spells`, `monsters`, `items`, `equipment`, and `all` |
| `--out <dir>` | required | Output directory |
| `--url <url>` | — | Detail URL for `class-features` / `species-features` |
| `--group <label>` | — | Group label from `/classes` or `/species` collapsible heading (exact, case-insensitive) |
| `--limit <n>` | — | Stop after N items (useful for testing) |
| `--cdp-url <url>` | `http://localhost:9222` | Chrome DevTools Protocol URL |
| `--delay <ms>` | `800` | Politeness delay between page loads |
| `--dry-run` | false | Enumerate list, print slugs, write nothing |
| `--verbose` | false | Log each URL as it is fetched |
| `--strict` | false | Abort on first parse failure instead of continuing |

Feature extraction target selection:

- For `class-features` and `species-features`, provide exactly one of `--url` or `--group`.
- `--group` scans:
  - [`https://www.dndbeyond.com/classes`](https://www.dndbeyond.com/classes) for `class-features`
  - [`https://www.dndbeyond.com/species`](https://www.dndbeyond.com/species) for `species-features`

**Output file naming:** `{out}/{source-or-ddb}-{type}.md`

Examples: `output/phb-2024-spells.md`, `output/mm-2025-monsters.md`, `output/ddb-class-features.md`

---

### `ddb lore`

Extracts lore from a D&D Beyond sourcebook into lore KB objects (one index object plus one lore object per chapter).

Sourcebooks live at URLs like:

- `https://www.dndbeyond.com/sources/dnd/<slug>`

For example, the Grim Hollow: Campaign Guide lives at:

- `https://www.dndbeyond.com/sources/dnd/ghcg`

Usage:

```bash
# Extract lore for a sourcebook
ddb lore --slug ghcg --title grim-hollow --out ./output/ghcg-lore.md

# Limit to the first N chapters while testing
ddb lore --slug ghcg --title grim-hollow --out ./output/ghcg-lore.md --limit 3
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--slug <slug>` | required | Source slug from the D&D Beyond URL (e.g. `ghcg` for `/sources/dnd/ghcg`) |
| `--title <title>` | required | Short title key used in KB ids (e.g. `grim-hollow`) |
| `--out <file>` | required | Output Markdown file path |
| `--limit <n>` | — | Stop after N chapters (useful for testing) |
| `--cdp-url <url>` | `http://localhost:9222` | Chrome DevTools Protocol URL |
| `--delay <ms>` | `800` | Politeness delay between chapter page loads |
| `--dry-run` | false | Print KB output to stdout without writing a file |
| `--verbose` | false | Log each URL as it is fetched |

**Output structure:**

- A single Markdown file containing:
  - One `lore.<title>` index object (e.g. `lore.grim-hollow`) listing all chapters.
  - One lore object per chapter, with ids like `lore.<title>-<chapter>-<slug>`, for example:
    - `lore.grim-hollow-12-magic-in-etharis`
    - `lore.grim-hollow-15-guide-to-dark-fantasy`

Each lore chapter body preserves headings, paragraphs, lists, and key figures from the compendium page, converted into Markdown.

---

## Resumability

The output file **is** the run state — no separate state file exists.

If `{source}-{type}.md` already exists when you run `extract`, the tool scans it for all `id:` values inside ` ```kb ` fences and skips those items. Only the remaining items are fetched and appended.

To start a run from scratch, delete the output file.

Interrupting mid-run (Ctrl-C) is safe — the file contains all successfully extracted blocks up to that point, and the next run will resume where it left off.

---

## Output format

Each run produces a single Markdown file:

````markdown
# DnD Beyond Extract: phb-2024 / spells
<!-- source:phb-2024 | type:spells | started:2026-03-04T10:00:00Z | enumerate:312 -->

```kb
---
id: spell.fly
tags:
  - source:phb-2024
  - level:3
  - school:transmutation
---
**Fly** · 3rd-level Transmutation

**Casting Time**: Action
**Range**: Touch
**Components**: V, S, M (a wing feather from any bird)
**Duration**: Concentration, up to 10 minutes

You touch a willing creature...
```

<!-- FAILED: some-broken-slug | reason: casting-time selector returned null -->
````

Failed items are recorded as HTML comments and do not block the run. The file is valid input for `lens kb extract` as-is — comments and non-fenced text are ignored.

---

## Importing into Lens

Once extraction is complete:

```bash
# From your Lens content repo (or datasets/dnd/ if building a dataset)
lens kb extract /path/to/output/phb-2024-spells.md
lens kb extract /path/to/output/mm-2025-monsters.md
```

This imports all `\`\`\`kb\`\`\`` blocks as a single pending transaction. Review with `git diff`, then `lens commit` to accept.

---

## Adding a new source

1. Add an entry to `config/sources.json`:
   ```json
   "xge": {
     "name": "Xanathar's Guide to Everything",
     "filterId": null,
     "types": ["spells", "items"]
   }
   ```
2. Run `ddb discover xge` to auto-populate the filter ID, or find it manually on `dndbeyond.com/spells` by inspecting the source filter options.
3. Run `ddb extract --type spells --source xge --out ./output`.

---

## Tag conventions

Tags follow Lens tag validation (`[a-zA-Z0-9_-]+` values only):

| Field | Tag format | Notes |
|-------|-----------|-------|
| Source | `source:phb-2024` | |
| Class feature parent | `class:druid` | Present on `feature.*` objects extracted from classes |
| Species feature parent | `species:aasimar` | Present on `feature.*` objects extracted from species |
| Spell level | `level:3` | `level:0` for cantrips |
| Spell school | `school:transmutation` | |
| Ritual | `ritual` | Flag tag — present only if ritual |
| CR (integer) | `cr:5` | |
| CR (fraction) | `cr:1-4`, `cr:1-2`, `cr:1-8` | `/` encoded as `-` (slash is invalid in tags) |
| Monster type | `type:humanoid` | |
| Monster size | `size:small` | |
| Habitat | `habitat:forest` | One tag per habitat |
| Item rarity | `rarity:rare`, `rarity:very-rare` | |
| Item type | `type:ring`, `type:wondrous-item` | |
| Attunement | `requires-attunement` | Flag tag — present only if required |
| Equipment category | `category:martial-melee` | |

Feature object IDs use:

- `feature.<class-or-species-slug>-<feature-slug>`

For class features, a leading heading prefix `Level (<n>):` is removed before generating the feature slug.

---

## Parser selectors

Parsers target DnD Beyond's CSS class names empirically. If D&D Beyond redesigns their site, selectors may break. Each parser file documents the selectors it relies on in a comment block at the top. Run a small extract with `--verbose --limit 3` to quickly spot broken parsers — failed items are appended as `<!-- FAILED: ... -->` comments.

Confirmed selectors (verified 2026-03-04):

| Parser | Key selectors |
|--------|--------------|
| list-page | `.listing-body [data-slug]` (items), `li.b-pagination-item-next a[href]` (next page) |
| feature-index | `.j-collapsible .ddb-collapsible__label` (group), `a.listing-card__link[href]` (detail URL) |
| feature-page | `section.primary-content h4` (feature headings), `h1` (parent name), pathname `/(classes|species)/<id>-<slug>` (parent slug) |
| spell-page | `.page-title` (name), `.ddb-statblock-item` (stats), `.more-info-content p` (description) |
| monster-page | `.page-title` (name), `.mon-stat-block__meta` (meta), `.mon-stat-block__attribute` (AC/HP/speed), `.ability-block__stat--{str\|dex...}` (ability scores), `.mon-stat-block__tidbit` (skills/CR), `.mon-stat-block__description-block` (traits/actions) |
| item-page | `.page-title` (name), `.item-info .details` (subtitle/rarity), `.more-info-content` (desc) |
| equipment-page | `.page-title` (name); current DOM: `.details-container-equipment` + table (Cost/Damage/Weight/Properties) + `.details-container-content-description-text` (desc); legacy: `.ddb-statblock-item`, `.more-info-content` |

To inspect the live DOM of a page using the CDP session:

```bash
# After ddb check confirms connection, open Chrome DevTools on the
# DnD Beyond tab and run in the console:
document.querySelectorAll('.ddb-statblock-item')
```

> **Development note:** Do not use named function variable assignments inside `page.evaluate` callbacks (e.g. `const f = () => {...}`). esbuild's `keepNames` transformation wraps them with `__name()` calls that are not defined in the browser context. Use only inline expressions and anonymous callbacks.`

---

## Project structure

```
tools/ddb-extract/
├── config/
│   └── sources.json        # Source slug → filter ID (edit to add new sources)
└── src/
    ├── cli.ts              # Commander entry: check, sources, discover, extract
    ├── browser.ts          # CDP connect, getPage, sleep with jitter
    ├── sources.ts          # Load/resolve/update sources.json
    ├── output.ts           # Create file, scan done-set, append block/failure
    ├── types.ts            # SpellData, MonsterData, ItemData, EquipmentData, etc.
    ├── parsers/
    │   ├── list-page.ts    # Generic paginated list enumeration
    │   ├── spell-page.ts   # DOM → SpellData
    │   ├── monster-page.ts # DOM → MonsterData
    │   ├── item-page.ts    # DOM → ItemData
    │   └── equipment-page.ts  # DOM → EquipmentData
    ├── formatters/
    │   ├── kb.ts           # slugifyKey, toTagSlug, encodeCR, wrapKbBlock helpers
    │   ├── spell.ts        # SpellData → ```kb block
    │   ├── monster.ts      # MonsterData → ```kb block
    │   ├── item.ts         # ItemData → ```kb block
    │   └── equipment.ts    # EquipmentData → ```kb block
    └── extractors/
        ├── base.ts         # ListExtractor<T> abstract class with run() orchestration
        ├── spells.ts
        ├── monsters.ts
        ├── items.ts
        └── equipment.ts
```
