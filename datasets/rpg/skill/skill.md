## Conventions of the `rpg` dataset

This project plays tabletop-style RPGs. The player directs; the AI authors.
Prep happens in `design` sessions, play happens in `play` beats, and time passes
in `advance`. Four kinds of object carry the weight of prep, and they are
constantly confused with one another:

- **An artifact** is what prep produces: something named, with a shape you can
  check mid-beat and a tell the player can feel. "Two concessions, then he
  walks" is an artifact; "let the conversation breathe" is not. An artifact
  usually is *not* its own object — one concrete line inside an `encounter.*` is
  an artifact.
- **A design module** (`design.*`) is instruction for *making* one: the stance,
  the structure, what makes it good, what it is not. Read by `design`, never by
  `play`. A module is not finished until it names an artifact and says how to
  check it.
- **A rules booklet** (`rules.*`) is how to *use* an artifact once the scene is
  live. Written for `play`. `design` reads booklets, but writes *against* them —
  nothing a booklet says should be copied into an emitted object.
- **A template** (`<type>._template`) is the stored shape: fields, ordering, tag
  policy. Templates are just more prompt; the fenced `kb` blocks a design
  session emits do not pass through them.

### Rules that break silently

**`rules.<type>` is a companion, reached by name, never by a tag.** Ship
`rules.encounter` and it is added to any play beat where an `encounter.*` object
is in scope, and to `design --module encounter` alongside the template. Tagging
it anywhere is a second, staleable copy of a link the machinery already makes.
Rules objects must not tag *each other*, or `--module` drags the whole shelf in.

**Deltas only.** A prepared object states what is different about *this* case —
the numbers, the triggers, the exceptions — and never restates how the mechanism
works. A re-explained rule is a copy that drifts, and at play time the model
cannot tell which copy is authoritative. It is not a tidiness argument: booklets
are already ~80% of a play prompt and a prepared encounter is under 200 tokens.
The object is where you say the thing no booklet could know.

**`-` is a facet separator, and the back never reaches play.** `front.problem`
is the play surface; `front.problem-prep` is the prep behind it. `design` and
`advance` facet-expand — naming an id also pulls its same-type `<id>-*` objects —
and `play` does not. Facets expand for *named* ids only (an ancestor pin,
`--pin`, `--module`, `kb_get`), never for ids arriving by `+`, a tag, a mention
or an include. Anything whose secrecy is load-bearing over time belongs in the
back; `ai:secret` only encodes a comment so a human does not read it by
accident, and guarantees nothing else.

**State lives in fronts, not scattered across objects.** The narrative tree
already records what happened. `lore.world` and its facets hold the frame that
does not change. A `front.*` holds what has not happened yet, with a timeline
anchor, and `advance` moves it by promoting prep into the visible text —
inventing nothing. When a front runs out of prep, `advance` says so and stops;
a person runs a design session.

**Which rules earn a registered module: system or situation.** A *system* is
big, self-contained, and announces itself in the fiction — a fight, a pursuit.
It earns a `[[dataset.modules]]` entry the model can pull mid-beat. A
*situation* — one hazard, a voyage, a specific negotiation — is known at prep
time and has no reliable trigger, so it travels inside the prepared object,
quoted into the scene rules or tagged so `encounter.foo+` brings it along. Every
registered module costs a catalog line on every beat, whether or not it is used.

**Reference objects stay out until they are in play.** Listing every ability a
character has tempts the model to make them use it. NPCs get their stat block;
players activate their own abilities and report the result, and `@spell.fly`
mid-prompt is how the full text reaches the model when it matters.
