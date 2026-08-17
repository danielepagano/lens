<!-- Design module. Usage: given to the design operator to guide one build-out task. Instructions for the AI, not an object a player creates. -->
# [DESIGN MODULE]: {TITLE}

This is a steering note for the design operator: how to turn story material that already exists into one playable part of the game.

Open with at most three lines: the title, what this module covers, and when to reach for it. Those lines are what `kb_with_tag design` prints, and they are the whole basis on which this module gets chosen or skipped.

A good design module makes five things clear:
- **The artifact it produces** — named, checkable, actionable, perceivable. This is the module's reason to exist.
- What to ask the user before starting
- What to look up in existing KB
- How to shape the output (and which `_template` describes it)
- Which failure modes to avoid

A module is not ready until it names an artifact. "Give the NPC a clear attitude" is guidance; "concession budget: 2, then he walks" is an artifact — it has a name, a value, and a stated consequence, a play operator can check mid-scene whether it has been spent, and the player can feel it spend. The artifact usually belongs as one line inside a larger object, not as a KB object of its own.

A module builds artifacts; it does not author the story they serve. The themes, the arc, the reveal, and who the story is about arrive as material from planning. If a module finds itself explaining how to invent those, that content belongs in `design.planning` instead — and what stays behind is the scheduling and mechanising job this module actually owns.

Say where a module's own type keeps its back, when that type tends to have one. Prep material that a later session needs and `play` must not read goes in a same-type `-` facet (`front.problem-prep`, `npc.vasa-plans`); the object itself stays the play surface. Most objects of most types never need one — only say so where it is genuinely the norm.

Core principles all modules share (do not restate them; the design operator already carries them):
- Story service: all content must connect to PCs and active fronts. No content in a vacuum.
- The fiction is given; the mechanism is yours. Load-bearing story facts are never invented, numbers and triggers and limits always are, and when a mechanism cannot be built without deciding a story fact, the module says so and stops.
- Modules are conversational stepping stones: a module may suggest creating objects another module develops. That is a user decision and a follow-up — never build them yourself.
- Running advice is deltas only: state what differs for this instance, never re-explain a procedure a `rules.*` booklet already covers.
