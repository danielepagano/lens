# Companion dataset (`companion`)

Enable with `datasets = ["companion"]` in `lens.toml`. Overview also in the [main README](../../README.md#getting-started).

## What this dataset is

It models **characters with more depth than a scene needs at a glance**, and it surfaces that as companion chat. The depth objects attach to any character, in any project; the chat-specific pieces are only two of the features below.

A companion is not a whole project. It is a handful of KB objects and a narrative tree where you chat.

## Features, and how to opt in

Every feature is opt-in **by construction**. There is nothing to configure: creating the object is the on switch, and not creating it is the off switch. That granularity is per character, because one project can hold a character with full depth and a dozen with none.

| Feature | Create | Kept current by | Running guidance |
|---|---|---|---|
| Depth and relationships | `psyche.<key>`, tagged `remember.psyche` | the remember pass, at summarize boundaries | `rules.psyche` |
| Concrete continuity | `life.<key>`, tagged `remember.life` | the remember pass | — |
| A chat surface for a character with no other home | `companion.<key>` | — | — |
| A counterpart who is a real person | `human.<key>` | — | — |
| Fourth-wall awareness | pin `meta.lens` | — | — |

**`psyche.<key>` is the main one.** It holds the core tension, what the character wants from the people around them, what earns warmth and what makes them go quiet, how their relationships stand, and what is currently moving. Relationships live here because they define a character as much as anything else does. `rules.psyche` — how to actually *play* someone whose psyche is in front of you — arrives on its own whenever a `psyche.*` object is in scope.

**`life.<key>` is the one to skip by default.** It tracks what is currently true: routines, agreements, running threads. Where a project already tracks that by other means — a schedule, a plan object, a timeline maintained by hand — a `life.<key>` becomes a second copy that drifts from the first.

## Attaching depth to a character

Tag the depth objects onto whatever object is that character's **surface**, once, at creation. After that, one character of pin syntax decides whether they arrive:

| Pin | What reaches the model |
|---|---|
| `<surface>.<key>` | surface only |
| `<surface>.<key>+` | surface, psyche, life — everything tagged there |
| `chat --as <surface>.<key>` | the `+` form, automatically |

So a scene that wants a light touch pins the surface bare, and a scene that is *about* the character pins it with `+`. Chat always takes the `+` form, which is right: a two-character exchange with an authored psyche is a depth scene by definition.

Note that `+` is one hop over **all** of an object's tags, so it also brings anything else tagged on that surface.

Where a character already has a surface object, use it. Do not create a `companion.<key>` alongside it — that is a second surface, and the two will disagree.

## Writing the objects

Write `companion.<key>`, `psyche.<key>`, and `life.<key>` in first person and in the character's own voice. Those files do double-duty: they present durable facts *and* prime the model toward the right voice, and a neutral checklist loses half of that. Write `human.<key>` as factual notes about the counterpart — not in the character's voice, and without inferring psychology for a real person.

Give each object a distinct job. Nothing that belongs on the surface goes in the psyche, and nothing that changes belongs on the surface, where remember cannot reach it.

`remember.*` tags go only on `psyche.*` and `life.*`. Tagging a surface object with one turns it into a journal.

## How to bootstrap a companion

1. Create a Lens project and add `datasets = ["companion"]` to its `lens.toml`.
2. Create a `human.<name>` object from `human._template`.
3. Create the companion either manually or with design:
   - **Manual:** create `companion.<name>` from `companion._template`; create `psyche.<name>` and `life.<name>` from their templates, tag them `remember.psyche` and `remember.life`, and tag their ids onto the companion.
   - **Assisted:** run `lens design --module companion "Help me create <name>"`, refine through the interview, then `lens design --end` to extract the objects.
4. Start chatting:

```bash
lens chat --as companion.mara --with human.adam "It's @now. We meet at the coffee shop as planned."
```

Use `@now` in a scene or message to insert the current day and approximate time in your timezone when real-world time matters.

To give depth to a character who already exists — in this project or from any other source — run `lens design --module psyche` instead. It reads the existing surface and builds only what attaches to it.

## Why memory is separate from the sheet

Summaries already keep the chat history. The psyche and life objects are for durable state that should shape future chats without replaying the archive — and they are separate from the surface because the surface is *authored* and they are *grown*. A fact that will change belongs where remember can reach it.

`remember.psyche` updates slow patterns: temperament, what they want, stress and repair, what someone is to them, growth edges. It skips one-off moods and banter.

`remember.life` updates concrete continuity: routines, rooms, objects, projects, promises, agreements, inside jokes, names, mundane preferences. It infers no psychology.

You can add more remember targets if you have a specific strategy, but don't overdo it: each one slows every summary and tempts the model to write the same update into all of them.
