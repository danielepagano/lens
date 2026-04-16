# Companion Dataset

## How it works

This dataset is meant to produce a “social companion” chat that can grow without drifting into amnesia or flattening as the conversation gets long.

Lens has three mechanisms that work together:

- **Pins (what the companion can feel right now)**: Lens builds chat context by crawling from the current narrative node upward and collecting *pinned* KB objects. In this dataset, you pin `meta.companion+` so the crawl pulls a compact “companion bundle” (identity + vibe + psychology notes + Lens orientation). The `+` matters: it expands linked dot-tags so a single pin can pull a small graph of objects.
  - You can edit any KB object and a copy in your project will be made; for example you can change `meta.vibe` for a different behavior, or not link `meta.lens` if you don't want your companion to meta-reflect about being an AI.

- **Auto-compression (keeping the present small and coherent)**: as a chat node grows, Lens can automatically collate older spans into a child section and replace them with a summary. Nothing is deleted; detail is pushed “down the tree” so the active surface stays short and usable.
  - You can also create multiple chat sessions as you: each will be summarized so the later sessions will know what happened (you can also summarize the summaries if this gets long with `collate`)

- **Remember system (quiet durable updates)**: when a chunk of chat is summarized (end of session, collate, or auto-compress), Lens will run a short *remember* pass if you pinned any KB objects whose tags include `remember.*`. In this dataset, remember instructions update:
  - `psych.bigfive`, `psych.attachment`, `psych.sdt` (slow personality / bond trackers)
  - `id.companion`, `id.human` (identity continuity)
  - Any other objects you want to create, for example your companion's virtual life details, which can be auto-updated by tagging them with `remember.life` for example (just tells the AI to remember "life", or you can create an object call that with more specific details)

Together, this creates a loop where the chat can stay playful and instinctive in the moment, while durable personality and relationship state gradually consolidates into structured psychology objects over time.

## How to bootstrap a companion

0. Create a Lens project and add `datasets = ["companion"]` to its `lens.toml`.
1. Edit `id.companion` and `id.human` with whatever details you wish.
  - If you don't want your chat messages to say "[Human]" rename id.human to id.your-name; remember to tag this object with `remember.human` so the the AI can update it.
2. Pin `meta.companion+` at the narrative root (or wherever you want this context to apply).
3. Start chat session. You can have a long session that auto-compresses, or many smaller sessions that `--end`.
  - Each session has a "Scene" setup that you can use when you return, or to simulate encounters in different places or the passage of time.
  - You can use @now in a scene setting or a message to replace it with the current day and approximate time in your timezone, to orient the AI around real-word time if that's a narrative need.

Example:

```bash
lens chat --as id.companion --with id.adam "It's @now. We meet at the coffee shop as we planned."
```