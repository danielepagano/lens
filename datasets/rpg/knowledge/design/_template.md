<!-- Design module. Usage: pinned by `lens design --module <key>` to steer one build-out task. Instructions for the AI, not an object the player creates. -->
# [DESIGN MODULE]: {TITLE}

{One or two sentences: what this module builds, and when a session should reach for it. These first three lines are all a tag search shows, so they have to be enough to choose on.}

A design module produces **artifacts**. An artifact is a named thing with a shape you can check: a clock with stated per-tick consequences, a concession budget, a walk-away condition, an initiative order, a stat roster. "Let the conversation breathe" is guidance, not an artifact — it gives `play` nothing to hold. A module is not finished until it names at least one artifact and says how to tell a good one from a bad one.

Every module makes five things explicit:

- **The artifact** — what this produces, in a shape a runtime operator can act on. Give the shape literally, as a block to copy, not as a description of a block.
- **What to ask the user** before starting.
- **What to look up** in existing KB, and with which tool.
- **How to check the result** — concrete questions with answers, not vibes. "Is the core question genuinely arguable?" is checkable. "Is it evocative?" is not.
- **What this is not** — the failure modes that look like success.

Core principles all modules share:

- **Story service.** Content connects to PCs and active fronts. No content in a vacuum.
- **Artifacts may share an object.** One encounter can carry a clock, a social ladder, and a stat roster. Split them into separate KB objects only when one of them outlives the other — a clock that runs for a month is a front's, not a scene's.
- **Modules mix.** A session opened on one module may pull another in for a single artifact (`kb_get design.clock`, or the user's `--include`). Say plainly in your text which other modules pair with yours, and let discovery find the rest: `kb_with_tag ["design"]` lists them all with their first three lines.
- **Modules are conversational stepping stones.** A module may suggest objects another module develops. That is always a user decision and a follow-up, never something you do yourself mid-session.
- **Running advice goes in the object, as deltas.** The default is to write how to run this thing into the thing itself — but only what is specific to it. The general procedure belongs in a `rules.*` booklet (`kb_with_tag ["rules"]`), and the object never restates it. "Alarm clock 4; a full clock means reinforcements, not detection" is a delta. Re-explaining how clocks work is a regression.
- **Front arc structure.** When creating fronts in any module, apply the three-layer structure (surface, adventure core question, twist) as embedded AI behavior — not as a player-visible workflow.

FIRST THREE LINES

Every KB object this repository ships — module, booklet, template, stat block, spell — reserves its first three lines for its own name and what it is for. Nothing else goes there. Tag searches and the `load_module` catalog read exactly those lines, so an object that opens with rules text is one nobody can find on purpose.
