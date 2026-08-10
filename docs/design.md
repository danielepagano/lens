# Lens — Design

> Filesystem-native, forward-only narrative trees and a knowledge store for modular AI-assisted creation with fractal summarization.

This document is the design reference for Lens. Getting started: [README](../README.md). Configuration: [configuration.md](configuration.md). Commands: [CLI reference](../lens/cli/README.md).

## Purpose and scope

### The problem

Language models attend best to what is near, recent, and explicit. A long story and a rich world quickly exceed what fits in one prompt and devolves into confabulation. Dumping everything into context wastes budget on irrelevant detail and dilutes attention on what matters now.

Lens solves **context composition under a token budget**: it curates what the model sees, at what resolution, so every token earns its place, and maximizes user agency during this process.

### What Lens is

Lens is a system for **controlled narrative simulations**: collaborative prose grounded in curated facts and shaped by explicit **operators**, not open-ended chat. An operator is similar to a specialized sub-agent, but it's not quite the same thing, as we shall see.

A narrative simulation is prose, but produced with improvisational structure: facts can ground it, randomness or rules can interrupt it, and human and AI turns alternate under clear contracts. Four mechanisms work together:

| Mechanism | Role |
|-----------|------|
| **Knowledge store** | Reusable facts — lore, rules, characters, memories — linked by tags into a graph |
| **Fractal narrative tree** | The story as an event log; parent nodes summarize, children hold detail |
| **Pinning** | Per-scene declaration of which KB objects are "in frame" for the model |
| **Operators** | Named verbs (`write`, `play`, `design`, …) with predictable behavior and preview/rollback |

The model sees *what matters now* at *the right resolution* and *for a specific progress step*, not everything ever written to just add more of it.

Fractal structure serves two goals at once: **prompt level-of-detail** (distant past in summary form) and **simulation depth** (zoom into child nodes where dice, rules, or other operators generated the outcome). The tree is both continuity mechanism and workspace — a readable overview above, reproducible detail below.

Narrative can run with little or no KB (read what happened before and keep writing), but consistency suffers as the world grows. KB objects can also **change over time** — added before and during creation, refined by planning, patched after summarizations.

### What Lens aims to do

- **Forward-only creation** — committed text is canon; the system evolves from the current state. While it does offer editing tools, this is not a tool to write a novel, it's a tool to see what the AI does next.
- **Long-term continuity** — hierarchical summarization: distant events as brief prose, nearby events in full detail (level-of-detail rendering for story).
- **Human–AI collaboration** through operators with preview, retry, and rollback — not one-shot generation.
- **Deliberate context curation** so behavior stays predictable as the world grows.
- **Multiple applications** on one core — companion chat, RPG play, fiction, world-building — via composable datasets and modules, not separate products.
- **A bit of fun** — besides the CLI, Lens ships with a desktop and mobile-friendly web UI with good visual feedback, media mixing, and optional “visual novel mode” (including companion chat with TTS).
- **Personal** — designed to run simply for one user, either locally or on a tiny cloud instance (often free-tier sized).

### What Lens is not

- A chat UI with a RAG bolted on 
- A game engine that resolves every rule
- A Markdown editor or editing assistant
- A system to get “real work” done. Lens optimizes for play and co-authoring; it won’t replace human craft, friends, or creativity.
- A promise of table-quality or videogame-polished output. At least with current models, we're more at the level of "neat, it's not always frustratingly dumb!" than "I don't need a real DM anymore".

Lens optimizes for **the experience of playing or co-authoring**, not publishable prose as the primary artifact.

## Two stores, one simulation

Lens separates **what the world is** from **what happened**.

**Knowledge** holds durable, reusable facts: people, places, rules, templates, plans. Objects are typed (`type.key`), tagged for retrieval and graph traversal, and optionally templated so operators know what shape to expect. Facts can be authored ahead of time or derived later (remember, design extract).

**Narrative** holds the simulation itself: prose at varying zoom levels, operator traces, and session transcripts. A node should read cogently at its level; detail lives in children, represented upstream as summaries.

This split is intentional. Putting "what happened" only in KB duplicates the tree and invites stale state. Putting all lore inline in narrative bloats every prompt and forgets details. Pins bridge the two: the tree records events; KB supplies what the model must know *right now* to continue faithfully.

**It can keep “secrets”** Models can only reason about what is written down and visible to users, which makes real surprises, schemes, inner thoughts, and secrets difficult to sustain.

Lens uses a simple system where HTML comments (usually not rendered in markdown) can be read and written by the AI, but if they are annotated as a secret they are stored encoded on disk and decoded for the LLM. The standard encoding is ROT13 so users can trivially peek — they’re more like spoiler tags than real secrets (because this is for fun).

### Datasets

**Datasets** are read-only KB bundles (mostly just markdown files). They can be either shipped with Lens (`rpg`, `companion`) or added at run-time from any repo, which allows hobbyist to create and share datasets for any IP (setting or game system) without Lens having to have that IP in its codebase. Mutating a KB item from a dataset just copies that version locally to the project.

Datasets are how Lens ships **behavior packs** — object ontologies, rule contracts, design modules, runtime meta pins — without forking the engine. Behavior can also be shaped by **modalities** (cross-cutting contracts applied across operators); see “Modalities” in [The Operator LLM pipeline](#the-operator-llm-pipeline). See [rpg-design.md](rpg-design.md) for layered rules/system/setting stacks.

#### Modularity (KB + optional Python)

Listing a dataset name in `[project] datasets` is enough for **knowledge**: Lens resolves the dataset directory (bundled with the install, a sibling repo, or `[dataset_paths]` in `lens.local.toml`) and merges its `knowledge/` into the project store with the usual shadowing rules.

When a dataset also needs **code** — CLI command groups, LLM command tools used mid-generation (e.g. by `design`), or prompt snippets — its `lens.toml` can declare an **extension**:

```toml
[dataset]
extension = "my_pkg"   # Python package at the dataset root; imported via sys.path
```

The package lives beside `knowledge/` in the dataset repo (no pip install). On CLI or server startup, Lens loads extensions only for datasets active in the current project. Bundled **`rpg`** operators (`play`, `advance`) remain in the Lens package; optional IP-specific tools (e.g. a private `lens-dnd` tree with `lens dnd balance` and `balance_encounter`) ship in their own dataset repos. Fly deploy copies external dataset trees into the image under `datasets/<name>/`, extension included.

Authoring details: [datasets/README.md](../datasets/README.md).

## Git-backed storage

Each Lens **project** is a content **git repository**. The repo _is_ the database:

| Git concept | Lens meaning |
|-------------|--------------|
| Unstaged changes | Pending operator transaction (preview you can easily rollback) |
| Staged changes | Accepted transaction, awaiting checkpoint |
| Commit | Checkpointed and cloud-stored canon |
| Branch | Alternate timeline, what-if |

This mapping is a storage design choice; the UI avoids git jargon (it uses “Save”, “Discard”, “Checkpoint”).

**Why git:** non-proprietary (it's your content in your repo), transparency (it's just Markdown you can editing with any tool), diff-based review of AI output, history and free cloud backups, and branches for exploration, all without a custom persistence layer.

**CLI-first:** the CLI is the primary interface; `lens/core/` holds all business logic. The server and UI are thin adapters over the same core.

**Single-transaction invariant:** at most one pending operator transaction per repo. New work auto-stages the previous. Every file mutation goes through `Storage` so ownership and rollback stay coherent.

**Direct user edits — the one exception.** The invariant is about *operator* work being reviewable as a unit. A user hand-editing a KB object or config is already the reviewer, and these edits arrive in bursts (clicking an HP spinner mid-scene), so wrapping them in transaction ownership buys nothing and silently accepts whatever preview happens to be pending. `Storage` therefore has three modes:

| `StorageMode` | Used by | On first write |
|---------------|---------|----------------|
| `OPERATOR` (owner set) | Operators, workflow steps, AI-driven `kb edit` | Stages the pending transaction only if it belongs to a *different* owner |
| `SYSTEM` (owner `None`) | Non-operator machinery: `init`, `use`, release/deploy, media + TTS writes, pins/vars/params | Stages any pending transaction |
| `DIRECT` (`Storage.for_direct_edit` / `session.new_direct_edit_storage()`) | Direct user edits: the KB write routes (save, create, delete, tag, template, copy, rename) | Stages nothing; instead stages *each file it writes*, immediately |

`DIRECT` writes leave every other pending change exactly as it was, so an unreviewed generation stays unstaged and Discard still reaches it. It is also the honest mode for mechanical repo maintenance — version bumps, migration writes, template refreshes — which can stage themselves instead of pretending to be operator work.

Front-matter writes (pins, vars, operator params) stay `SYSTEM` for now: they land in narrative files, which the pending transaction usually owns anyway. `lens use` stays `SYSTEM` too — switching the active narrative is a structural change, not a hand edit. Both are revisitable; the mode is a per-call-site choice, not a property of the file type.

**Same-file conflict:** if the pending transaction already touches the file being edited, staging it would split an operator's own work across the staged/unstaged boundary — worse than either alternative. In that case `DIRECT` does not stage at all: the edit stays unstaged and merges into the existing transaction, and Discard takes both. The user is editing an object the operator is mid-way through changing, so treating the edit as part of that transaction is the honest reading.

Generated content never uses `DIRECT`. The AI-driven KB edit (`POST /kb/edit`) stays a reviewable transaction, exactly like an operator, because it is something you want to retry and revert.

**Stateless tooling:** Lens needs filesystem access, git credentials, and LLM configuration — not a running database. A deployment can wrap a single commit lifecycle.

**Three ways to use a project:** (1) browse and hand-edit Markdown — Lens optional if structure is respected; filesystem uniqueness is mostly self-enforcing; (2) invoke operators at the cursor with preview/retry; (3) stage and checkpoint. For large resets, **git checkout or branch** restores narrative *and* knowledge together; narrative-only **rewind** truncates the tree but does not roll KB back by itself.

Project layout (`knowledge/`, `narrative/`, `lens.toml`, optional prompt overrides) is documented in the [README](../README.md).

## Media mount

Binary assets (images, video, audio, any files) live **outside git**. The repo stores prose, KB, and **references** to media; blobs go on an optional **mount**.

**Opt-in:** set `[project] mount_point` in `lens.toml`. Without it, `lens media` is unavailable and the UI has no media browser.

**Backends:**

| Form | Role |
|------|------|
| Relative or absolute local path | Directory under or beside the project; you organize the tree |
| `s3://bucket/prefix` | Object storage (S3-compatible); typical for deployed projects; enables `--ref` images for generation via presigned URLs |

**Why not git:** assets are large and churn-heavy (and sometimes just a cache); keeping them out of the content repo keeps clones fast and diffs meaningful, and avoids running out of free git space (cloud services offer free tiers for S3-compatible storage that is usually well above what a single Lens user would need). Narrative nodes embed mount-relative paths (`/mount/file/…`); the server proxies bytes from the mount so that the S3 buckets used can stay private.

**Layout (conventional, not enforced):** user files anywhere on the mount; Lens writes `generated/<slug>/` (image batches + sidecars) and `tts-cache/…` (speech chunks keyed by text). Attach paths are always **mount-relative**, not repo-root paths.

**Metadata:** each media file may have a flat YAML sidecar (`photo.jpg.yml`) alongside it on the mount, holding arbitrary key/value facts (character, expression, generation prompt, …) plus path-derived reserved keys. A `composite: background` or `composite: foreground` key marks a file as one layer of a Visual Novel scene; `lens media attach BG --fg FG` (or the web UI's media carousel, which prompts for the complementary layer automatically) embeds both as a single composite attachment that VN playback renders as background-plus-centered-foreground.

Details: [README](../README.md) (`mount_point`, `[[image]]`, `[[speech]]`); commands in [lens/cli/README.md](../lens/cli/README.md).

## Fractal narrative

### Tree and cursor

The narrative is a **tree of nodes**, each prose at one level of detail. Zoom levels are semantic, not fixed — chapter, session, encounter, or combat round depending on the project. At every level the node should read cogently on its own; sections of parent prose may be **summaries of child nodes**, not transcripts of everything beneath.

Sections create child nodes; closing a section moves detail down and replaces the span in the parent with an **LLM summary**. Users don't necessarily have to plan levels of details ahead of time, however, as they can collect any content (manually, or have the AI select a good chunk for you) and create a section ("collate") at any time: so, keep writing at the current zoom, then compress side quests or digressions when the parent node gets too dense. If the user doesn't even do that, the system can be setup to find long context window and automatically carve out details for you, so you have a linear chat where old memories may go fuzzy, but nothing important is forgotten, even without a KB. Lens calls this "compression" (instead of compaction) because it's more targeted, it aims for narrative coherence, not just "summarize my full context window".

So, ancestor context in prompts therefore behaves like level-of-detail. At chapter 3, scene 4, beat 3 the model sees chapters 1–2 as summaries, earlier scenes in chapter 3 as summaries, beats 1–2 of the current scene as summaries, and the cursor beat in full — not a flat dump of every leaf ever written.

Lens assumes **forward append** at a single **cursor** — the current insertion point. Sub-node sessions (chat, play, design) move the cursor into a child until close summarizes back to the parent. **Edit** is the exception: it rewrites an existing range (history remains in git). Most other operators append or restructure without silently rewriting canon.

### Annotations

Operator state lives in [Markdown comment](https://www.markdownguide.org/hacks/#comments) annotations and node front matter (pins, vars, operator params). Rendered prose hides this machinery — readers see summaries and story, not pipeline artifacts.

The design choice: **story files remain human-readable** and render clean Markdown, while still being machine-orchestrated. You can edit canon by hand if you respect structure; Lens automates the boring consistency work.

## Context composition

Context assembly is the heart of Lens. Operators do not hand-craft prompts; they declare a **crawl spec** and inherit a standard assembly order.

### Pinning

**Pins** answer: *for this scene, what facts should the model know?*

`kb_pin` / `kb_unpin` on node front matter inherit root → cursor (deeper wins; unpins cancel ancestors, e.g. "we're having a moment, forget about the RPG rules"). Per-call pins and `@type.key` mentions add ephemeral scope. **Vars** (dynamic values you can insert by id) and **params** (pin operator parameters you don't want to specify all the time, like a custom reasoning level for this one node) inherit the same way — substitution and operator defaults without repeating configuration every invocation.

Pinning is how Lens keeps prompts small without losing fidelity: only objects declared in-frame enter context, plus their linked expansions when requested.

### Crawl

**Crawl** walks the tree from cursor toward root and produces two streams:

1. **Knowledge** — pinned objects, deduped, root → cursor (global grounding before local scene)
2. **Narrative** — visible ancestor prose, annotations stripped, same order (fractal history)

Special-semantic pins like Chat Participants and session modules merge via crawl transforms — without duplicating pin semantics.

### Narrative slices

Narrative collection always follows the **lineage spine** — the direct parent chain from some start point to the cursor. Sibling subtrees are never walked; fractal summarization is the contract that rolled-up parent prose already carries what mattered from branches closed via section/play.

**KB pins** are different: they always resolve along the **full** ancestor chain (root → cursor), regardless of narrative window.

An optional **slice anchor** `(node, line_end)` narrows *where* the spine starts and *how much* of that node counts:

| | Narrative window |
|---|------------------|
| **No anchor** (default for `write`, `play`, …) | Full text of every node on the spine from **narrative root** → cursor |
| **With anchor** (e.g. `advance`) | Spine from anchor → cursor; on the anchor node only text from `line_end` onward; full text on nodes in between |

Anchors are **operator-owned**: the operator that needs a temporal or logical cutoff finds and validates its anchor (e.g. `advance` locates the previous completed advance on the same timeline) — see [rpg-design.md](rpg-design.md).

### Prompt assembly

Assembled messages follow fixed **attention order**:

1. System — operator role and constraints  
2. Relevant knowledge — crawled KB  
3. Previous events — ancestor narrative (summaries + recent detail)  
4. Current passage — cursor node (or the conversation turns it parses into)  
5. Live state — KB objects tagged `state` (see below)  
6. Task — instruction, user input, tools  

Stable instructions and distant grounding come first; immediate task last. Order is a design choice, not an implementation detail.

### Live state: mutable objects render at the tail

Most KB objects are durable facts, and the assembly order above puts them early precisely because they do not change: everything from the system prompt through the last completed turn is a stable prefix a provider can cache.

Some objects are the opposite. An initiative tracker, a live mood, a scratchpad the model reads each beat — the user *intends* to update these as the session runs. Placed in `[RELEVANT KNOWLEDGE]` they sit in the prefix, so every edit invalidates the entire prompt behind them, and they land far from the decision they inform.

Tagging an object **`state`** diverts it to the **tail** — after the last transcript turn, immediately before `[TASK]`. Both pressures agree on that slot: the object costs only its own tokens uncached per beat (a cost that is unavoidable, because the content genuinely changed), and live state is the most decision-relevant material in the prompt.

Mutability is a property of the **object**, not of how it entered scope, so the divert is orthogonal to pinning. It applies identically whether the object arrived as an ancestor front-matter pin, a session module, a rules companion, or an `@` mention — one pass over the finished render graph (`_divert_state_components`, `lens/core/context.py`), running after id dedup so an object that is both pinned and mentioned still lands exactly once. `expansion_policy_from_tags` is the existing precedent for tags driving render behaviour.

Nothing gains write powers here. State objects are player-maintained; `play` still only appends narrative. The user is responsible for keeping them accurate across rollback, retry, and rewind — the same discipline already applied to a character sheet.

`lens explain` reports the block as `live_state`, classified **volatile**, so the per-beat cost is visible rather than inferred.

### Inspecting the composition

Curation only beats retrieval if you can see the curation. `lens explain` (and `GET /{slug}/explain`) assembles the prompt at a cursor exactly as the operator would — same crawl spec, same modality pins, same render transforms — and then reports it instead of sending it: every component with the block it lands in, its bytes and estimated tokens, its share of the total, and why it is there (a pin on a named ancestor, a `+` expansion, an `@` mention, a rules companion, a session module, a modality). Totals are given per block and overall.

This makes pin curation an engineering activity rather than a vibe: a stat block costing 400 tokens in a scene it no longer belongs to is visible, not inferred. The command is read-only by construction — no transaction, no model call, so it works with no LLM configured. Token counts are an estimate (bytes over a fixed divisor); byte counts are exact.

In the web app the same report is a modal, opened by the **context** button beside the cursor pins or by `/structure-explain [address] [line]`: a stacked bar of the prompt blocks over the per-component breakdown, with a tokens/bytes toggle and an operator selector — switching `write` to `play` at the same cursor visibly changes the bar, because auto-pins and required modalities differ. Blocks are read from the payload rather than assumed: when a passage parses into turns there is no `current_passage` block at all, only `conversation`. The report is read-only in the UI too; changing a pin is still `pin-kb`, on the ancestor the row names.

## Operational modes

The same storage, crawl, and generation pipeline supports three modes that alternate in real use. Separating them keeps prompts focused: planning mutates KB shape; generation appends story; management compresses and extracts durable state.

### Planning

Create or refine **objects and structure**, not live scene prose.

- **`design`** — conversational KB workspace; swappable modules (`design.encounter`, `design.companion`, …). The model can use tool calls to explore the KB and generate its content; the KB is not directly authored, instead the LLM emits fenced `kb` blocks into the narrative for the user to review, iterate on, and even directly edit. When the design session is completed, these blocks become KB item upserts.
- **Direct KB work** — manual edit, tag, template, bulk extract. This can be done directly in the file system, or via CLI or web UI.
- Specialized: **`advance`** (RPG) — calendar and `front` updates when time passes outside play

Planning lives in prep sub-nodes that don't leave a summary, so they are "invisible" to future spine crawls, but the context of the story (if any) is still visible to the design operator.

### Generation

Produce **narrative or dialogue** at the cursor.

- **`write`** — general prose from authorial intent (your prompts are NOT part of the output, they just steer)
- **`chat`** — in-character speech; the user can play the part of one of the characters (and using KB, the other AI-controlled character can have specific knowledge and attitude towards the user's character)
- **`play`** — the AI is the GM, and the user can speak as the player, or in-character as one or more PCs

During generation, durable KB usually stays fixed; the tree absorbs what happened. Patches flow through summarize boundaries, not every turn.

### Summarization and management

Compress detail and maintain **long-horizon continuity**.

Closing a section, session, or collate range summarizes prose upward. **Auto-compress** may trigger after inline generation when a node grows too large. The **Remember** system allows KB object to opt-in at being updated at one of these boundaries, meaning the LLM can autonomously patch their long-term memory; each object can have a specialized prompt to remember in a faceted manner; this separated what happened in chat (summary) from what durably affected a story element, so that there are fewer inconsistencies as the world moves forward. The companion dataset, for example. uses this system to track a companion's psychological state separately from the narrative, using the remember prompts like an autonomous sub-conscious process.

Management is where Lens converts ephemeral generation into durable structure without rereading entire archives.

## Operators and transactions

An **operator** is a named contract: given context and input, it mutates narrative and/or KB, with previews before canon.

### Operators vs agents

Colloquially an **agent** is an autonomous loop — perceive, plan, act, repeat until a goal — often with dynamic retrieval and implicit approval of each step. A Lens **operator** is deliberately not that: it is a **user-invoked verb** whose orchestration Lens owns (crawl, prompt assembly, persist shape, hooks). The LLM is a step inside the operator, not the planner of the whole workflow.

| | Operator | Agent (typical) |
|---|----------|-----------------|
| Initiation | You run `/write`, `/play`, … | Often goal-driven, self-chaining |
| Context | Declared (pins, modules, crawl) | Often inferred or open-ended RAG |
| Output | Git diff until staged/checkpointed | May apply opaquely |
| Scope | Narrow job per verb | General problem-solving |
| State | The project (tree + KB) | Often separate session memory |

Some operators contain a **bounded tool loop** mid-generation (`design` lookups, `compress` choosing a collate range) — agent-like locally, but still one explicit invocation with fixed persist rules. Multi-step work is **you alternating modes** (plan → play → summarize), not a standing autonomous actor.

### Shape

| Shape | Idea | Examples |
|-------|------|----------|
| **Inline** | Stream into cursor node | `write`, one-shot `chat`, `play` beats |
| **Sub-node / session** | Child node until `--end` summarizes | `section`, chat/play/design/advance sessions |
| **Mutation** | Claim a range, propose replacement | `edit` |
| **Structure** | Refactor existing prose into hierarchy | `collate`, `compress` |

**Session operators** share one lifecycle (open sub-node → append blocks → close with summary and optional KB extract/remember). They support **swappable modules** — one active `design.*` or `rules.*` KB object pinned in session front matter at a time, switching context without new operator types.

**Command tools ≠ operators.** Operators are invoked by you or the UI with full crawl and persist rules. **Command tools** are small helpers the model may call *inside* one generation loop — read-only KB lookups during `design` (`kb_get`, `kb_list_tags`, `kb_with_tag`), or whitelisted `kb_patch` during remember. They do not spawn other operators. Speed-first operators (`write`, `play`) skip them. `compress` is different again: a bespoke `compress_collate` tool returns a line range and Lens runs `collate` in code.

**Multi-step, not chaining.** A continuing `write` can leave an open annotation (continue/retry before close). Session `--end`, auto-compress, and remember are follow-up work in core — separate LLM passes under one user invocation, not one operator dispatching another as an agent would. A thin **WorkflowRunner** schedules these passes with named steps so the stream, CLI, and UI can show the plan and current phase instead of an undifferentiated token flow.

**Mutation (`edit`)** uses a two-phase claim: stage tags around the target range, then propose replacement in a new pending transaction that removes the tags. Rollback applies a compensating transaction. Pending state is always grep-visible in the repo; operators must not leave dangling claim tags.

Rollback semantics differ by shape (discard unstaged inline work vs. compensating mutation claims) but the user-facing rule is uniform: nothing is canon until staged and checkpointed.

Command-level detail: [lens/cli/README.md](../lens/cli/README.md).

## The Operator LLM pipeline

Three concerns, one contract:

| Concern | Question |
|---------|----------|
| **Gather** | What context does this invocation need? |
| **Transform** | What must change in text before/after the model sees it? |
| **Generate** | How is the model called and output persisted? |

Operators stay **thin**: they declare prompts, session shape, tools, and `CrawlSpec` differences — not whether secret decode or `@roll` runs. The core owns the pipeline orchestration so it stays consistent across verbs and adapters.

### Pipeline at a glance

Most operator invocations follow the same execution order:

**Invocation** → **Gather (crawl)** → **Assemble messages** → **Generate (LLM + tool loop)** → **Compose artifacts** → **Post/refine** (`workflow_post`, then one `workflow_refine:<modality_id>` per contributing modality) → **Persist** → **Optional tail steps** (e.g. `auto_compress`, session-end `remember`)

Each stage is independently visible in the preview (as a workflow step), and optional tail work can be skipped without discarding the successful earlier steps.

### Gather: crawl spec → crawl result

**Gather** is crawl (+ spec knobs: extra pins, slice anchor, modules, participants). Operators declare the knobs; crawl performs the walk and yields a structured result:

- **Knowledge** — pinned objects, deduped, root → cursor
- **Narrative** — spine slices toward the cursor (summaries + recent detail)
- **Crawl graph** — a structured context graph that transforms can inspect and modify before rendering

### Assemble: crawl result → model messages

Operators do not hand-craft prompts. They typically call the standard prompt assembly using the crawl result:

- Base messages are formed from system prompt + assembled knowledge + assembled narrative + task instruction.
- Modalities may then add prompt framing and constraints (system addenda) after the base assembly.

### Generate: the `LlmRun` envelope and tool loop

**Generate** is the `LlmRun` envelope: resolve model config (no per-operator opt-out), apply any pre-transforms needed for instruction/task text, assemble messages, then stream or complete (with a bounded tool loop when needed). The output is captured as structured generation artifacts rather than a single flat string (or, for tool-first single-round flows, a final payload).

### Artifacts composition: persist vs stream vs log

Generation output is split into prose vs tool-call segments at the stream layer, then composed for three targets:

- **Persist** — `compose_for_operator()` writes segments into the narrative file (interleaved fences or audit-comment wrappers).
- **Stream (SSE)** — `compose_for_stream()` / `compose_tool_call_for_stream()` controls what the preview channel shows (raw fences, summary-only, or structured typed events).
- **Log** — `format_tool_event_for_log()` produces compact tool summaries (name, arg keys, byte counts) instead of full fence dumps.

### Transforms: prompt vs crawl-graph (and where `@` expansion happens)

**Transforms** in Lens are split into two layers:

- **Prompt transforms** (pre-generation): small, deterministic rewrites on the operator’s instruction/task text before it is embedded into the prompt. These handle things like expanding `@` syntax (vars, KB mentions, rolls) in a consistent way without duplicating logic across operators.
- **Crawl-graph transforms** (assembly-time): edits to the *gathered context graph* before it is formatted into model messages (reordering, injecting derived context, or rewriting blocks to match a contract).

Separately, there are post-generation behaviors (post-processing and refine passes) that operate on composed prose after generation; those are driven by modalities and scheduled as workflow steps (see below).

**Three transforms, three meanings** — easy to conflate:

| Mechanism | What it changes |
|-----------|-----------------|
| `@` storable pre-pass | `transform_prompt(..., STORABLE)` on prompts stored in narrative or fed into `crawl()` — vars, inline-tag KB, rolls, `@now`; KB `@` mostly survives for `mention_pins`. Applied automatically via `Operator.run_inline` / `transform_storable_prompt`. |
| `@` render (crawl graph) | `AtExpansionTransform` during `assemble_prompt` — reference KB blocks, slices, tag policy. Automatic for all crawl-based `LlmRun` paths. |
| `@` flat (no crawl) | `transform_prompt(..., FLAT)` — force-inline all `@` in one string (e.g. `media generate`). |
| `edit` mutation | Existing prose via staged claim + replacement |
| **Remember** | KB objects after **summarize**, on the passage being compressed — not a post-transform on every inline generation |

### Modalities: cross-cutting contracts, applied consistently

**Modalities** are Lens’s cross-cutting composition layer for LLM behavior.
Operators define *what verb you invoked* and *how it persists*. Modalities define *shared contracts* that should apply across many verbs and datasets: formatting rules, additional grounding, optional post-processing, and other reusable behavior that would otherwise be duplicated across operators.

Concretely, modalities can contribute (depending on what’s active at the cursor):

- prompt framing and constraints (system addenda),
- extra crawl pins/unpins and crawl-graph transforms (what is gathered and how it is presented),
- optional command tools for a given model loop,
- post-processing and optional refine passes that operate on the composed prose before persist.

The engine resolves the active set by merging built-in defaults, front matter along the ancestor chain, and operator requirements. The same modality composition applies to inline generation and to session beats that call the model (`design`, `chat`, `play`, `advance`). This is why datasets can “feel different” without a new operator surface: they can tune prompts and register modalities that layer the right contracts everywhere.

**Speech markup** is one example of a modality: when enabled, it guides the model to emit TTS-oriented control tags according to a selected `[[speech]]` grammar, and it can run a lightweight post-generation refine pass to improve tag quality without changing the meaning of the text. If refine cannot be applied safely, Lens keeps the pre-refine text and surfaces a warning rather than failing the whole invocation.

**`media_attach`** is another example, and a different shape of contract: rather than guiding the main model's own output, its refine pass runs a small, separate classify LLM against the *composed* prose to pick which image best fits the beat just written, from a label set discovered at runtime (an anchor media search's undecided facets — see [configuration.md](configuration.md#modalitymedia_attach) and issue #51) rather than any fixed ontology. The main model is never told this modality exists; `prompt_addenda` is deliberately empty, because a classifier that scores the model's *actual* output is a better judge of what art fits than a model asked to describe its own scene while still writing it. The picked image is attached before the response text, matching a manual VN attach, and its chosen facet values are recorded in a markdown-comment annotation the main model never sees, so the next beat's classify pass gets its hysteresis anchor without polluting the story prompt.

**Refine passes are plural and independent.** Every active modality that wants one gets its own `workflow_refine:<modality_id>` step, each separately skippable — declining the sprite swap should not also decline TTS markup. Nothing flows from one pass to the next and no modality may depend on running before or after another, so the execution order is not part of the contract. Because the passes do share one body of text, each spec is rebuilt immediately before its own step runs rather than all up front: a pass that captured line positions earlier would otherwise be merging into text another pass had already shifted.

### Hooks and workflows: scheduling follow-up steps without turning operators into agents

**Orchestration hooks** fire from core operator entry points only (`post_inline` → auto-compress; `summarize_close` → remember). Hooks may spawn follow-up `LlmRun` passes or collate work. **WorkflowRunner** is the thin scheduler that wraps those sequences — it does not replace `LlmRun` or turn operators into agents. Operators and hooks still declare *what* runs; the runner owns *when*, *in what order*, and *how skip, retry, and abort propagate*.

Typical workflows (each step is one or more `LlmRun` calls, exposed under a stable `step_id`):

| Flow | Steps (examples) |
|------|------------------|
| Inline `write` / `play` / `chat` | `generate` → optional `workflow_post` → optional `workflow_refine:<modality_id>` (one per contributing modality) → `persist` → optional `auto_compress` |
| Session `--end`, section close, collate | `summarize` → `remember` → structural close |
| Manual compress | `compress_select` → collate chain |

**Why it exists:** follow-up tail steps fail independently in practice (remember after a good summary, auto-compress after a long generation). The **step plan in the preview** is the product surface: you see what will run and can decline optional tail steps *before* paying for them — not recover after a monolithic stream fails.

**Workflow outcomes:** a workflow is **`failed`** if any step failed. It is **`partial`** when nothing failed but at least one step completed with non-fatal **warnings** (degraded-but-acceptable results). It is **`success`** only when every completed step succeeded with no warnings. (**`cancelled`** remains reserved for abort/rollback paths.)

#### Transactions and step boundaries

Multi-step operators still share **one pending (unstaged) transaction** for the invocation. The runner does **not** stage between steps — staging is an explicit user action (“Save”), not workflow machinery.

| When a step finishes | What happens |
|----------------------|--------------|
| Step succeeds | Its writes land in the pending transaction (unstaged). Later steps may add more unstaged work on top. |
| Step succeeds **with warnings** | Same as success for the transaction; **`workflow_outcome`** may be **`partial`** so the UI keeps the plan visible. |
| Step is **skipped** | It never runs (or is not retried). Earlier successful steps stay in the pending transaction. |
| Step is **aborted** mid-run (`abort_rolls_back`) | The whole operator pending transaction is discarded via `execute_rollback`. |
| User **Discard** | Same as rollback — rejects the entire preview regardless of workflow state. |

Steps that only stream (e.g. `generate` on a fresh write) **commit to disk only on success** — abort mid-stream writes nothing.

#### Skip, retry, and abort — do not conflate

These are three different controls:

| Control | Meaning | Rollback? | Workflow continues? |
|---------|---------|-----------|---------------------|
| **Skip** (per step in the plan) | “I don’t want this optional step.” | No — completed steps stay | Yes — next steps run (e.g. skip `remember` → `close` still runs) |
| **Retry** (after retryable failure) | “Run this step again.” | No | Yes — only that step is re-invoked |
| **Abort / Cancel** (stream stop during a dirty step) | “Stop now — this step may have partial side effects.” | Yes, when the step has `abort_rolls_back` | No — remaining steps are not run |
| **Discard** (transaction UI) | “Reject this entire preview.” | Yes — always | N/A |

**Skip** is forward-only and is the main reason the plan exists. Optional tail steps (`remember`, `auto_compress`, …) are marked `skippable` in the plan; the UI shows a Skip control on each planned skippable step. Skip can be signaled while an earlier step is still running (e.g. skip `remember` during `summarize`).

**Abort** is for in-flight steps that mutate state incrementally (KB patches during `remember`, collate during `auto_compress`). Those steps set `abort_rolls_back`: stream Cancel sets `cancel_event`, the step stops, and core calls `finalize_workflow_outcome()` at workflow entry points to run `execute_rollback` on the operator transaction when `rollback_pending`. Use **Skip** instead when you simply don’t want the tail step — abort is the escape hatch when you’re already mid-mutation.

#### Examples

**Session end — skip remember:** Plan is `summarize → remember → close`. You skip `remember` from the preview. Summarize completes (summary held in memory for this run), remember is marked `skipped`, **close runs** and inserts the summary into the parent. Session closes without KB memory updates.

**Session end — abort mid-remember:** Remember is running and may have applied partial KB patches. Cancel aborts remember and **rolls back the whole session-end transaction** — do not try to keep summarize while dropping partial remember.

**Write — skip auto-compress:** Plan is `generate → auto_compress`. Generation completes (unstaged). You skip `auto_compress`. The raw generation stays in the pending preview.

**Write — abort mid-compress:** Collate may have partially mutated the node. Cancel rolls back the **entire** write invocation transaction (generation included). To keep generation without compress, use **Skip**, not Cancel. The UI Cancel label during auto-compress should communicate whole-preview discard when a dirty step is running.

#### Adapters

The CLI and the web UI are just two adapters over the same core workflow semantics. Both surfaces can present the step plan, allow skipping optional work, and keep a successful-but-degraded run visible by treating warnings as **`partial`** rather than as a failure.

The envelope covers narrative generation via ``run_llm`` and tool-first single-round flows (e.g. compress) via ``run_llm_final``. New operator code routes through the envelope; multi-step sequences route through the runner.

Implementation: `lens/core/context.py`, `llm_run.py`, `prompt_transforms.py`, `crawl_transforms.py`, `lens/core/modalities/`, `hooks.py`, `workflow_runner.py`.

## Example applications

Same core; different datasets, templates, meta pins, and modules.

### Companion chats

The **companion** dataset targets **continuing dyadic roleplay** — not assistant Q&A. A compact play surface (`companion.*`), counterpart notes (`human.*`), and split memory objects (`remember.psyche` vs `remember.life`) keep voice, bond patterns, and concrete continuity in separate channels.

Fractal summarization handles transcript history; remember updates memory on session close so later chats inherit durable state without replaying the archive. Guide: [datasets/companion/README.md](../datasets/companion/README.md).

### RPG play

The **rpg** dataset targets **directorial play in an open-ended textual game** — player intent, GM-authored outcomes, player-side mechanics. Planning (`design`) builds encounters and fronts; play executes; advance moves calendar pressure.

**Encounter objects are scene scripts**, not operator modes: combat, social, chase, and hybrids differ in preparation, not in which verb you invoke. Context stays scene-sized via pins and summaries; nested sections focus heavy fights.

Full treatment — authority model, object templates, fronts, timelines, adventure design: **[rpg-design.md](rpg-design.md)**.

## Product shape

Lens is **CLI-first for development**; the server and UI exist so the same project works on a phone or browser without losing git semantics.

The intended UX is a **Markdown editor with commands**: most of the surface is reading and previewing story; a command strip navigates the tree, invokes operators (`/write`, `/collate`, `/tx-checkpoint`), and supports section zoom without git jargon in the UI ("Checkpoint", "Save", "Discard"). During generation, a **workflow status** strip shows the step plan (generate, summarize, remember, …) with **Skip** on optional planned steps and **Retry/Skip** when a retryable step fails — not a single "streaming…" label for the whole invocation. Stream **Cancel** aborts the in-flight step (rolling back when the step is dirty); **Discard** rejects the whole preview. The web UI groups commands by role — transactions, structure, pins, media, generative narrative — matching how the backend separates concerns.

Prompt text itself is layered: built-in defaults, optional prompt packs (allow both customization and localization), project overrides (`prompts/prompts.toml`, copy-on-write). Operators reference keys, not embedded prose in code paths users cannot change.

## Design invariants

Short list of non-negotiables that fall out of the above:

1. **Narrative is canon for events; KB is canon for reusable facts** — don't duplicate event logs in objects without a remember/extract reason.
2. **Context is declared, not inferred** — pins, modules, and crawl specs determine prompts; operators don't scrape the repo ad hoc.
3. **Resolution matches relevance** — fractal summaries + slices; full ancestry is the default for append operators, not for every planner.
4. **Preview before canon** — one pending transaction; git diff is the review surface.
5. **Operators are thin** — semantics and prompts vary; gather/transform/generate do not.
6. **Core is adapter-agnostic** — CLI, server, and tests call the same functions.
7. **Orchestration lives in core** — hooks, follow-up LLM work, and step scheduling (`WorkflowRunner`) do not belong in route or CLI wrappers. Workflow **Skip** is forward-only; **Abort** rolls back dirty in-flight steps; do not conflate them or stage between steps.
8. **Remember is summarize-bound** — durable KB patches run on passages being compressed, not on every streamed token.

## Appendix: Prompt editing heuristics

Guidance for system prompts, design modules, and dataset KB. Preserve the lesson, not wording tied to one experiment.

### Core framing

- Prompts **steer**, they do not program. Dense conceptual cues beat long procedural scaffolding.
- The prompt's own prose should sound like the desired output. Flat policy-copy induces flat output.
- Specificity beats virtue words ("be vivid" needs situational meaning).

### Practical rules

- Compress long "how to work" sections to load-bearing constraints only.
- Audit for **format-locking** — numbered templates and rigid section sequences make the model pick form first.
- Name failure modes directly ("what this is not") when cheaper than more exhortation.
- Use examples sparingly for known recurring failures, not to pad length.
- Favor **goal-shaped** user instructions ("why does this scene fall flat?") over topic-shaped ones ("write about this scene").
- Treat prompts over a few hundred words as suspect.

### Lens-specific

- Keep machine-sensitive rules explicit (output formats, tag conventions, exact anchors).
- Prefer behavioral guidance over narrated workflows the model might echo as headings.
- Distinguish transferable craft from domain voice — companion flirtation lessons do not belong in RPG or summarization prompts wholesale.
- When editing dataset prompts, preserve domain voice; improve shape and failure handling without sanding character away.

### Good outcomes

- The model sounds like it understood the job, not like it followed a checklist.
- Output varies with the scene while staying inside boundaries.
- Constraints hold without template-locking the response.
- Shorter prompts feel stronger because remaining tokens do more work.

## References

| Topic | Location |
|-------|----------|
| Setup, config, media | [README](../README.md) |
| CLI commands | [lens/cli/README.md](../lens/cli/README.md) |
| RPG extension | [rpg-design.md](rpg-design.md) |
| Companion dataset | [datasets/companion/README.md](../datasets/companion/README.md) |
| Web UI / server | [lens/server/README.md](../lens/server/README.md) |
