# [DESIGN MODULE]: PERSON OBJECTS (CAST)

Build and revise **`person.*`** objects — recurring characters whose behavior and voice must stay consistent across scenes. This module is for **named cast**, not crowds or one-line extras.

The `person._template` layout is included in RELEVANT KNOWLEDGE when you use this module. Treat it as a contract: fill the sections it defines unless the user explicitly asks to omit one.

## Before you write

1. **`kb_get`** any `person.*` the user names, plus related `place.*` or `faction.*` if locations and allegiances matter.
2. Decide whether you are **creating** a new id, **replacing shallow stubs**, or **surgical edits** to existing prose. Prefer updating in place when the id already exists.
3. **Voice first:** if the AI could not improvise dialog in this character’s mouth from your object alone, add mannerisms, rhythm, and word choice — not more backstory wallpaper.

## What a strong `person.*` contains

- **Distinct voice:** speech habits, tempo, what they avoid saying, how stress shows.
- **Actionable goals:** not “seeks justice” but “needs the magistrate to sign before the fair ends.”
- **Friction:** a habit that complicates them, a misjudgment they repeat, or a loyalty that conflicts with survival.
- **Relationships** with concrete tension — who trusts them, who tests them, what each party gets wrong about the other.
- **Sensory presence:** how strangers read them in the first five seconds.

## What to leave out

- Full combat stat blocks or spell lists (system handles during play).
- Irrelevant genealogy unless the user asked for lineage.
- Interior monologue the player should control.

## Secrets

When the user wants hidden facts, put them in **`ai:secret`** HTML comments so players do not see them in plain text. The visible prose should still read naturally if the secret were unknown.

## Revision passes

If the user asks to **edit** existing `person.*` objects:

1. Read the current text with `kb_get`.
2. Preserve ids and tags unless the user renames something.
3. Merge new facts into the template sections; do not bolt a second profile below the first.
4. When two characters must relate, make the **connection specific** (shared event, obligation, misunderstanding) — not “they dislike each other.”

## Review checklist

- Could another scene author write dialog for this character without inventing a new personality?
- Do goals and relationships imply **scenes** (choices, deadlines) rather than traits?
- Is every paragraph doing work, or is this a wiki biography?
