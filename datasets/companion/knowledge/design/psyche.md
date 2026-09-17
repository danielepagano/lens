# [DESIGN MODULE]: PSYCHE

Give a character depth: interiority, what they want from the people around them, and where their relationships stand. Use when a character already has a surface object somewhere and needs to become someone who can change.

This module does not create the character. It finds the object that already presents them — whatever type that is — and builds the depth that attaches to it. If no such object exists, say so and ask for one first rather than inventing a second surface.

## What This Module Produces

- `psyche.<key>`: the depth object, tagged `remember.psyche`.
- A tag added to the character's existing surface object pointing at `psyche.<key>`, so it arrives whenever the character does.

Optionally, and only when asked:

- `life.<key>`: concrete continuity, tagged `remember.life`. Decline it by default. Where the project already tracks what is currently true about this character by other means, a `life.<key>` becomes a second copy that drifts from the first.

`psyche._template` is in RELEVANT KNOWLEDGE when this module is active, and `rules.psyche` shows what the object has to support at scene time. Write against both.

## Interview Flow

Work conversationally. Read the surface object first and do not re-ask what it already answers.

1. **Tension.** Find one internal contradiction — wants closeness but distrusts being needed; likes being seen but hates being interpreted; wants to be kind but is bored by softness. This is required. Without it the character collapses into whoever is easiest to agree with.

2. **Want.** What are they short of, and what are they after from the people in front of them? Abstract virtues are not answers. "Wants to matter to someone who has options" is.

3. **Friction.** What earns warmth, what makes them go quiet or sharp, where they push back, how they come back after a rupture. If the user offers a trait like "guarded but loyal", turn it into a condition with a consequence before writing it down.

4. **Relationships.** For each person who recurs, one block: this character's read of them, what they want from them, what is unfinished. Ask whose view it is — a psyche holds *their* read, which can be wrong, unfair, or out of date, and saying so out loud usually improves it.

5. **Growth edges.** What is currently moving. Not goals someone else assigned them.

## Object Shaping Rules

Write in first person, in the character's own voice. A psyche that reads like case notes has given up half of what it is for.

Seed every section from the interview; sparse is fine, blank is not — a blank object tells the remember pass to invent, which is how a psyche turns into a diary.

Keep relationships to people who will recur. One scene with a stranger is not a relationship.

Nothing that belongs on the surface goes here. Appearance, voice, and hard boundaries are paid for on every turn the character appears and already have a home.

## KB Output Rules

`kb_add psyche.<key>` — the seeded depth, opening with the character's name.
Then `kb_tag psyche.<key> tags=["remember.psyche"]`.

Link it from the surface with `kb_tag <surfacetype>.<key> tags=["psyche.<key>"]`, which changes tags only and leaves that object's body untouched.

Never tag a surface object with `remember.*`.

## Failure Modes To Avoid

- Creating a second surface object for a character who already has one.
- Producing a psyche so long it costs more than the character is worth in a scene.
- Filling every section rather than the ones the interview actually reached.
- Writing relationships as facts about the other person instead of this character's read of them.
- A `life.<key>` nobody asked for.
