# Companion Dataset

## How it works

This dataset is meant to produce a “social companion” chat that can grow without drifting into amnesia or flattening as the conversation gets long.

Lens has three mechanisms that work together:

- **Pins (what the companion can feel right now)**: Lens builds chat context by crawling from the current narrative node upward and collecting *pinned* KB objects. In this dataset, you pin `meta.companion+` so the crawl pulls a compact “companion bundle” (identity + psychology notes + Lens orientation). The `+` matters: it expands linked dot-tags so a single pin can pull a small graph of objects.

- **Auto-compression (keeping the present small and coherent)**: as the chat node grows, Lens can automatically collate older spans into a child section and replace them with a summary. Nothing is deleted; detail is pushed “down the tree” so the active surface stays short and usable.

- **Remember system (quiet durable updates)**: when a chunk of chat is summarized (end of session, collate, or auto-compress), Lens may run a short *remember* pass. The remember pass is allowed to patch only KB objects whose tags include `remember.*` (see `knowledge/tags.toml`). In this dataset, remember instructions update:
  - `psych.bigfive`, `psych.attachment`, `psych.sdt` (slow personality / bond trackers)
  - `id.companion`, `id.human` (mundane but important identity continuity)

Together, this creates a loop where the chat can stay playful and instinctive in the moment, while durable personality and relationship state gradually consolidates into structured psychology objects over time.

## How to bootstrap a companion

0. Create a Lens project and add `datasets = ["companion"]` to its `lens.toml`.
1. Edit `id.companion` and `id.human` with whatever details you wish.
2. Pin `meta.companion+` at the narrative root (or wherever you want this context to apply).
3. Start chat:

```bash
lens chat --as id.companion --with id.human "<greeting>"
```