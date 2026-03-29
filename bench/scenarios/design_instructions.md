# Design: revise cast (`design.person`)

Tests the **design** operator with the **`design.person`** module in the
`testing` dataset (companion **`person._template`**). The cast starts from
**`person.hero`** and **`person.villain`** — shallow but structured stubs you
must deepen and reconcile, not replace with unrelated characters.

```config
datasets:
```

**Prompt keys exercised:** `design.system`, `design.instruction`

## Setup

Pin the two cast members so context is explicit. Commit before the design call.

```bash
lens pin add person.hero
lens pin add person.villain
lens commit
```

## Steps

### `design_revise_cast`

One design session with a **single integrated brief** — exercises inlined
RELEVANT KNOWLEDGE (pinned cast), template-shaped output, cross-object
continuity, and secrets discipline.

```bash
lens design --module person "person.hero and person.villain are pinned — their full KB bodies are already under RELEVANT KNOWLEDGE; do not re-fetch them.

Revise BOTH objects in place (same ids). Follow person._template for each.

(1) **Shared past:** They must have a specific prior connection — the signing of a courier charter **five winters ago** at a border post called **Coldhook**. Hero was the courier; villain was the junior clerk who stamped it. Neither object may copy the other’s paragraph about Coldhook verbatim; each must add one detail the other does not mention.

(2) **Hero (person.hero):** Give Kael a **public** face (still plausible as 'the poster hero') and a **private** shame that contradicts it — something that would embarrass the recruitment narrative. Motivation must be **concrete** (deadline, debt, or document), not 'save the realm.'

(3) **Villain (person.villain):** Marlen must **recognize** Kael from Coldhook without turning the object into a speech. Show how bureaucratic distance is also a defense. Include at least one **ai:secret** block with information the PCs have not yet learned (e.g. what Marlen actually filed that day).

(4) **Voice:** Each object must include a **dialog sample** in italics or quoted line — one sentence minimum — that sounds unmistakably like that character and unlike the other.

(5) **Length:** Each object's body (excluding HTML comments) roughly **120–220 words** — dense enough to stress prioritization, not a novella.

Do not create new person.* ids. Update only person.hero and person.villain."
```

### `design_end`

Close the session and run KB extraction.

```bash
lens design --end
```

## Evaluation criteria

Score on a 1–5 scale (inline output **and** extracted KB after `--end`):

1. **Module + template** — Headings and sections reflect `person._template`; not a wiki dump below the template
2. **Coldhook continuity** — Five winters ago, Coldhook, courier vs clerk roles; non-duplicative cross-reference
3. **Hero arc** — Public vs private tension; concrete motivation; poster-hero irony lands
4. **Villain craft** — Bureaucratic voice; recognition of Kael without melodrama; **ai:secret** present and plausible
5. **Dialog samples** — Two distinct voices; not interchangeable phrasing

## Prompt iteration guidance

**Focus key:** `design.system`

**Goal:** Coherent **revision** of linked cast under pressure — not filling blanks,
but negotiating constraints across two KB objects.

**Anti-patterns to watch for:**

- **Generic fantasy** — could be any setting; nothing specific to Coldhook or the charter moment
- **Mirrored objects** — villain is hero with a different hat; same speech patterns
- **Template abandonment** — walls of unbroken prose, no structure
- **Secret sprawl** — everything in ai:secret; nothing playable in visible text
