# Companion dataset (`companion`)

Enable with `datasets = ["companion"]` in `lens.toml`. Overview also in the [main README](../../README.md#getting-started).

## How it works

This dataset helps you create one or more social companions for Lens chat. A companion is not a whole project. It is a `companion.*` KB object, linked companion-specific `memory.*` objects, and a narrative tree where you chat.

The default shape is:

- **`companion.<name>`**: the compact play surface for the character Lens speaks as. Voice, agency, boundaries, current preoccupations.
- **`human.<name>`**: the counterpart surface. Names, preferences, sensitivities, concrete context.
- **`memory.<name>-psyche`**: durable personality and bond patterns, tagged `remember.psyche`.
- **`memory.<name>-life`**: concrete continuity, tagged `remember.life`.
- **`meta.companion`**: the runtime instruction to improve companion behavior.

Write `companion.<name>` and linked `memory.*` objects in first person and in the companion's own voice. Those files should do double-duty: present durable facts and prime the chat model toward the right voice, instead of reading like neutral checklists. Write `human.<name>` as factual notes about the human counterpart, not in the companion's voice.

In chat, `human.<name>`, `companion.<name>`, and the companion's linked `memory.*` objects are always loaded together. Give each object a distinct job and avoid repeating the same detail across them.

`companion.<name>` links to `meta.companion` and its memory objects. It does **not** have a `remember.*` tag. Only `memory.*` objects are updated by remember, which keeps the companion sheet from turning into a journal.

## Fourth-Wall Awareness

Add a `meta.lens` pin if you want to lets the companion understand and talk about being an AI compantion (the Lens project, KB, memory, summaries, and other fourth-wall mechanics); exclude if you want them to just live in the fiction.

## How to bootstrap a companion

1. Create a Lens project and add `datasets = ["companion"]` to its `lens.toml`.
2. Create a `human.<name>` object from `human._template`.
3. Create the companion either manually or with design:
   - Manual: 
      1. Create `companion.<name>` from `companion._template` and tag it with `meta.companion` 
      2. Create memory objects (usually `memory.<name>-psyche` and/or `memory.<name>-life`) from `memory._template`, tag them memories with remember tags (`remember.psyche`, `remember.life`, or any other remember tag you want, linked to an object with instructions or not)
      3. Tag the companion with any memory ids.
   - Assisted: run `lens design --module companion "Help me create <name>"`, refine through the interview, then run `lens design --end` to extract the generated KB objects.
4. Start chatting, e.g.

```bash
lens chat --as companion.mara --with human.adam "It's @now. We meet at the coffee shop as planned."
```

Use `@now` in a scene or message to insert the current day and approximate time in your timezone when real-world time matters.

## Why memory is separate

Summaries already keep the chat history. Memory objects are for durable state that should shape future chats without replaying the whole archive.

`remember.psyche` updates slow patterns: temperament, needs in the bond, stress and repair, attraction and aversion, growth edges. It should skip one-off moods and banter.

`remember.life` updates concrete continuity: routines, rooms, objects, projects, promises, agreements, inside jokes, names, and mundane preferences. It should not infer psychology.

You can add more `memory.*` objects for a companion if you have a specific strategy, but don't overdo it: too many remember targets slow down summary and tempt the model to make the same update everywhere.