# D&D Beyond Reference Extractor — Design Document

## Purpose

A CLI tool (`lens ddb`) that extracts D&D 2024 reference objects (spells, monsters, magic items, equipment) from D&D Beyond into Lens KB-formatted Markdown files, without any LLM involvement. The tool is deterministic and mechanical: DOM parsing → structured data → KB file. Source parameterization means adding a new sourcebook costs zero code changes.

---

## Approach Analysis

Two approaches are on the table.

### Approach A: List/Filter Pages

D&D Beyond exposes paginated list views per content type, filterable by source:

```
https://www.dndbeyond.com/spells       ?filter[]=source:702&page=1
https://www.dndbeyond.com/monsters     ?filter[]=source:702
https://www.dndbeyond.com/magic-items  ?filter[]=source:702
https://www.dndbeyond.com/equipment    ?filter[]=source:702
```

The list gives slugs and canonical detail-page URLs. Each detail page (`/spells/2618987-fly`, `/monsters/17271-goblin`) is the authoritative rendering of that entity — same DOM structure regardless of which sourcebook it came from.

**Extraction pattern**: enumerate list → collect URLs → fetch each detail page.

### Approach B: Source Book Pages

D&D Beyond also presents sourcebooks as navigable digital books:

```
https://www.dndbeyond.com/sources/dnd/phb-2024
https://www.dndbeyond.com/sources/dnd/phb-2024/spells-a-z
```

These pages have a TOC and render book-chapter content. In some cases they inline content; in others they embed the same detail pages via iframes or link out.

**Extraction pattern**: parse TOC → follow chapter links → extract entities per chapter.

### Decision: Approach A wins

| Criterion | List Pages (A) | Source Books (B) |
|---|---|---|
| DOM consistency across sources | ✅ Identical detail page layout for all sources | ❌ Chapter structure varies per book |
| Adding a new source | One config entry (source ID) | Requires validating TOC structure |
| Content completeness | ✅ Canonical entity page, richest data | ⚠️ Book rendering may elide or reformat |
| Type separation | ✅ Natural: /spells, /monsters, /items | ❌ Types mixed across chapters |
| Resumability | ✅ Slug-level tracking trivially | ⚠️ Chapter-level granularity only |
| Robustness to DnD Beyond updates | ✅ Detail page is the product, last to change | ❌ Book UI is marketing surface, changes often |

**Source books as discovery only**: The one value of Approach B is that `https://www.dndbeyond.com/sources/dnd/phb-2024` can be scraped once to *verify* a source slug and discover its numeric filter ID, which then feeds into Approach A. This is implemented as `lens ddb discover <source-slug>`.

---

## Browser Automation Strategy

D&D Beyond is a React SPA. Content is rendered client-side after authenticated API calls; a simple HTTP client sees a blank shell. A real browser is required. The user is already authenticated in their running Chrome — we must use that session, not start a fresh incognito with no cookies.

### Recommended: Playwright via CDP Remote Debugging

```
# User launches Chrome once with debugging port open:
google-chrome --remote-debugging-port=9222 --profile-directory=Default

# Or with a shell alias in their profile (add to .bashrc / .zshrc):
alias chrome-debug='google-chrome --remote-debugging-port=9222 --profile-directory=Default &'
```

The tool connects to the running instance:

```typescript
import { chromium } from 'playwright';
const browser = await chromium.connectOverCDP('http://localhost:9222');
const context = browser.contexts()[0]; // existing session, existing cookies
```

This gives us the user's full authenticated session with zero credential handling. No cookie exports, no profile copying, no auth flow in the tool.

**Fallback (if Chrome isn't running with debug port):** The tool detects the connection failure and prints a clear one-liner startup instruction, then exits. Optionally: `--launch` flag launches a persistent context at a known profile path, but this requires Chrome to not already be running.

**Headless consideration**: Run headless (`headless: false` on the connect, since it's an existing window) — leave it visible so the user can observe and intervene. For a large batch (300 spells), `--headless` could be added as a flag later.

---

## Repository Location and Stack

**Location**: `tools/ddb-extract/` within the Lens repository.

Not integrated into the `lens` CLI proper — it's an ancillary data-prep tool with heavy dependencies (Playwright). It exposes its own `ddb` binary that can be invoked standalone or aliased.

```
tools/ddb-extract/
├── package.json
├── tsconfig.json
├── src/
│   ├── cli.ts              # Commander.js entry point
│   ├── browser.ts          # CDP connection logic
│   ├── sources.ts          # Source catalog + ID resolution
│   ├── extractors/
│   │   ├── base.ts         # ListExtractor<T> interface
│   │   ├── spells.ts       # Spell list pagination + detail parsing
│   │   ├── monsters.ts     # Monster list + stat block parsing
│   │   ├── items.ts        # Magic item list + detail parsing
│   │   └── equipment.ts    # Equipment list + detail parsing
│   ├── parsers/
│   │   ├── list-page.ts    # Shared: extract [title, slug, url] from any list page
│   │   ├── spell-page.ts   # DOM → SpellData
│   │   ├── monster-page.ts # DOM → MonsterData
│   │   ├── item-page.ts    # DOM → ItemData
│   │   └── equipment-page.ts
│   ├── formatters/
│   │   ├── kb.ts           # Any*Data → KB Markdown (header + content)
│   │   ├── spell.ts        # SpellData → formatted Markdown body
│   │   ├── monster.ts      # MonsterData → formatted Markdown body
│   │   └── item.ts         # ItemData → formatted Markdown body
│   ├── output.ts           # Output file writer: create header, append kb block, append failure comment, scan for done-set
│   └── types.ts            # Shared type definitions
├── config/
│   └── sources.json        # Source slug → filter ID mapping (user-maintained)
└── README.md
```

**Dependencies**: `playwright`, `commander`, `slugify`. Dev: `typescript`, `tsx`. No LLM dependencies, no network calls outside of Playwright-mediated DnD Beyond navigation.

---

## CLI Design

```bash
# Extract spells from PHB 2024; writes phb-2024-spells.md in ./kb/
ddb extract --type spells --source phb-2024 --out ./kb/

# Extract monsters from Monster Manual 2025
ddb extract --type monsters --source mm-2025 --out ./kb/

# Extract all types from a source (one file per type)
ddb extract --type all --source phb-2024 --out ./kb/

# If ./kb/phb-2024-spells.md already exists, the run automatically resumes
# (appends remaining items); delete the file to start fresh

# Discover a source: navigate to its page, extract source ID, update sources.json
ddb discover phb-2024

# List known sources
ddb sources

# Validate connectivity (check CDP port, check DnD Beyond auth)
ddb check
```

**Global flags**:
- `--cdp-url` — default `http://localhost:9222`
- `--delay <ms>` — politeness delay between page loads, default 800ms
- `--dry-run` — enumerate list, print slugs, write nothing
- `--verbose` — log each page load and parse result

---

## Extraction Flow

```
1. ddb check
   └─ Connect to CDP → verify DnD Beyond session (navigate to /account)

2. Resolve source ID
   └─ Look up slug in sources.json → get numeric filter ID
   └─ If not found: run discover first

3. Determine output file path: {out}/{source}-{type}.md

4. Resume detection
   └─ If file exists: scan for all `id:` values inside ```kb blocks → "done" set
   └─ If file does not exist: create it, write header comment with metadata

5. Enumerate list pages (always, even on resume — list is the ground truth)
   └─ GET /spells?filter[]=source:{id}&page=1  (alphabetical order by default)
   └─ Extract: [(slug, detail-url, habitats[]?), ...]  ← habitats from environment-tag on list page
   └─ Follow "next page" until exhausted
   └─ Deduplicate slugs (some items appear in multiple sources)

6. Subtract "done" set → work queue (order preserved = alphabetical = deterministic)

7. For each item in work queue (with delay):
   └─ Navigate to detail URL
   └─ Wait for content render (type-specific selector)
   └─ Run type-specific DOM parser → structured data
   └─ Run formatter → ```kb block string
   └─ APPEND block to output file immediately (crash-safe: partial file = valid resume)

8. On parse failure:
   └─ Append `> FAILED: {slug} | reason: {error message}` to output file
   └─ Continue

9. Report: N extracted, M skipped (resumed), K failed
```

---

## Output File Format

Each run produces **a single Markdown file** named `{source}-{type}.md` (e.g., `phb-2024-spells.md`) containing a metadata header followed by sequential ` ```kb ` fenced blocks — one per extracted object. The file is consumed as-is by `lens kb extract`, which handles all tag processing and KB import; the tool need not concern itself with directory structure or tags.toml.

```
phb-2024-spells.md       ← one run, all spells from that source
mm-2025-monsters.md      ← one run, all monsters
phb-2024-items.md
phb-2024-equipment.md
```

The `--type all` flag runs each type sequentially, producing one file per type (not one combined file — keeps imports granular and resumable independently).

### File structure

```markdown
# DnD Beyond Extract: phb-2024 / spells
<!-- source:phb-2024 | type:spells | started:2026-03-04T10:00:00Z | enumerate:312 -->

```kb
---
id: spell.aid
tags:
  - source:phb-2024
  - level:2
  - school:abjuration
---
[content]
` ``

```kb
---
id: spell.alarm
tags:
  - source:phb-2024
  - level:1
  - school:abjuration
  - ritual
---
[content]
```

> FAILED: some-broken-slug | reason: casting-time selector returned null
```

Failures are plain HTML comments between blocks — ignored by `lens kb extract`, visible in any editor.

### Object key derivation

The `key` is the DnD Beyond slug with its numeric prefix stripped: `2618987-fly` → `fly`. If two slugs from different editions would produce the same key (unlikely), retain the numeric prefix.

## KB Object Examples

### Spell

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

You touch a willing creature. The target gains a Fly Speed of 60 feet for the duration. When the spell ends, the target falls if it is still aloft, unless it can stop the fall.

**Using a Higher-Level Spell Slot.** You can target one additional creature for each spell slot level above 3.
```

Tags: `source:`, `level:` (0 for cantrips), `school:`, `ritual` (flag tag, no value, if applicable).

### Stat block (monster)

Multiple habitats → multiple separate tags. `lens kb` can then find `habitat:forest` across all monsters correctly; a comma-joined string would be unfindable.

```kb
---
id: stat.goblin
tags:
  - source:mm-2025
  - cr:1/4
  - type:humanoid
  - size:small
  - habitat:forest
  - habitat:grassland
  - habitat:underdark
---
**Goblin** · Small Humanoid (Goblinoid), Typically Neutral Evil

**AC** 15 (Leather Armor, Shield) · **HP** 7 (2d6) · **Speed** 30 ft.

| STR | DEX | CON | INT | WIS | CHA |
|-----|-----|-----|-----|-----|-----|
| 8 (−1) | 14 (+2) | 10 (+0) | 10 (+0) | 8 (−1) | 8 (−1) |

**Skills** Stealth +6
**Senses** Darkvision 60 ft., Passive Perception 9
**Languages** Common, Goblin
**CR** 1/4 (50 XP; PB +2)

**Nimble Escape.** The goblin can take the Disengage or Hide action as a bonus action on each of its turns.

---
**Actions**

**Scimitar.** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. *Hit:* 5 (1d6 + 2) slashing damage.

**Shortbow.** *Ranged Weapon Attack:* +4 to hit, range 80/320 ft., one target. *Hit:* 5 (1d6 + 2) piercing damage.
```

Tags: `source:`, `cr:`, `type:`, `size:`, one `habitat:` tag per environment span.

**Note on habitat**: Confirmed present as `<span class="tag environment-tag">Forest</span>` on both list and detail pages. Collect at list-enumeration time so no extra detail-page load is needed for this field.

### Magic item

Attunement is a presence/absence flag tag — `requires-attunement` if the item requires it, nothing if it doesn't. No boolean field.

```kb
---
id: item.ring-of-protection
tags:
  - source:phb-2024
  - rarity:rare
  - type:ring
  - requires-attunement
---
**Ring of Protection** · Ring (Rare, Requires Attunement)

You gain a +1 bonus to AC and saving throws while wearing this ring.
```

```kb
---
id: item.bag-of-holding
tags:
  - source:phb-2024
  - rarity:uncommon
  - type:wondrous-item
---
**Bag of Holding** · Wondrous Item (Uncommon)

This bag has an interior space considerably larger than its outside dimensions...
```

Tags: `source:`, `rarity:`, `type:`, `requires-attunement` (flag, only if true).

### Equipment

```kb
---
id: equipment.longsword
tags:
  - source:phb-2024
  - category:martial-melee
---
**Longsword** · Martial Melee Weapon

**Cost** 15 gp · **Damage** 1d8 slashing · **Weight** 3 lb
**Properties** Versatile (1d10)
```

Tags: `source:`, `category:` (simple-melee, martial-melee, simple-ranged, martial-ranged, armor, shield, …).

---

## Parser Design Notes

Each parser is a TypeScript function:

```typescript
async function parseSpellPage(page: Page): Promise<SpellData>
async function parseMonsterPage(page: Page): Promise<MonsterData>
async function parseItemPage(page: Page): Promise<ItemData>
```

**Implementation guidance for Claude Code**: Before writing the parsers, use the Claude in Chrome integration (or the tool's own `--dry-run --verbose` mode) to inspect the actual DOM of one example page of each type. DnD Beyond's class names are obfuscated or functional — `page.evaluate()` to extract `document.querySelector('[data-testid="spell-name"]')` etc. The correct selectors must be empirically determined. Design the parsers to fail loudly with a descriptive error (including the URL) rather than silently emit partial data.

**Hardening principle**: If any required field parse returns null/undefined, the extractor writes the entry to `.ddb-failed.txt` and continues rather than crashing the entire run. A `--strict` flag makes it abort on any parse failure.

---

## Source Catalog (`sources.json`)

```json
{
  "phb-2024": {
    "name": "Player's Handbook 2024",
    "filterId": 702,
    "types": ["spells", "items", "equipment"]
  },
  "mm-2025": {
    "name": "Monster Manual 2025",
    "filterId": 823,
    "types": ["monsters"]
  },
  "ghpg": {
    "name": "Greyhawk Player's Guide",
    "filterId": null,
    "types": ["spells", "monsters", "items"]
  }
}
```

- `filterId` is the numeric ID used in DnD Beyond's filter query parameter. It is `null` until `ddb discover {slug}` populates it.
- `types` constrains what the `--type all` flag will attempt for this source.

The `discover` command navigates to `https://www.dndbeyond.com/sources/dnd/{slug}`, then navigates to `/spells?filter[]=source:`, opens the source dropdown, and reads the option value for the matching source name. This is the one place where some interactive navigation may be needed — the command should open the filter UI and allow the user to confirm visually if automation fails.

---

## Resumability

The output file is the state. No separate state file exists.

On startup, if `{out}/{source}-{type}.md` already exists, the tool scans it for all `id:` values within ` ```kb ` fences (a simple regex suffices — no YAML parsing needed at this stage). Those IDs constitute the "done" set. The enumerated slug list is then filtered against this set, and only the remainder is fetched and appended.

Since items are enumerated in alphabetical order (DnD Beyond's default list sort) and appended in that same order, a partially-written file represents an unambiguous prefix of the full run. The tool doesn't need to parse or validate the existing content beyond extracting IDs — it only ever appends.

To restart a run from scratch: delete the output file.

---

## Rate Limiting and Politeness

- Default delay: 800ms between navigation calls
- Jitter: ±200ms random to avoid pattern detection
- On HTTP 429 or timeout: exponential backoff (2s, 4s, 8s) up to 3 retries, then fail-and-continue
- Total estimated time: 300 spells × ~1.5s = ~7.5 minutes per run — acceptable for an occasional extraction task

---

## Implementation Checklist for Claude Code

1. **Scaffold**: `npm init`, TypeScript config, Commander.js entry, Playwright devDependency
2. **`ddb check`**: CDP connect, DnD Beyond auth verification
3. **`ddb sources`**: Read and pretty-print sources.json
4. **`ddb discover <slug>`**: Navigate to source, extract filter ID, write back to sources.json
5. **List page enumerator**: Generic paginator for `/spells`, `/monsters`, `/magic-items`, `/equipment` — extracts title, slug, URL per row; handles "next page" navigation
6. **Detail page parsers**: One per type — empirically determine selectors from live pages before coding; use `page.evaluate()` for DOM access
7. **KB formatters**: One per type — produce the ` ```kb ` block with `tags:` array as documented; each habitat gets its own tag entry; `requires-attunement` is a presence/absence flag tag
8. **Output file manager** (`output.ts`): create file + header comment on first run; regex-scan existing file for `id:` values (done-set); append ` ```kb ` blocks; append `<!-- FAILED: ... -->` comments
9. **Error handling**: Per-item try/catch → failure comment appended to file; `--strict` flag aborts on first parse failure
10. **`ddb extract` orchestration**: Wire all of the above; progress logging with count and ETA

**Selector discovery process** (step 6): Before implementing parsers, run a one-off script that navigates to one example page of each type and calls `page.evaluate(() => document.body.innerHTML)` to inspect the raw HTML. Identify stable selectors — DnD Beyond demonstrably uses named semantic CSS classes for at least some elements (e.g. `span.environment-tag` for monster habitats, confirmed present on both list and detail pages). Prefer `data-*` attributes and semantic class names over utility/hashed classes. Document the selectors used as comments in each parser file so they're easy to audit after a DnD Beyond redesign.

**Known confirmed selectors**:
- Monster habitat: `span.tag.environment-tag` — present on list *and* detail pages; extract at list-enumeration time.

