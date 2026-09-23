## Conventions of the `companion` dataset

This dataset models characters with more depth than a scene needs at a glance, and
surfaces that as chat. Its features are opt-in **by construction**: creating the
object is the on switch, not creating it is the off switch, and the granularity is
per character. There is nothing to configure.

| Object | Holds | Grown by |
|---|---|---|
| `psyche.<key>` | core tension, wants, friction and repair, relationships, growth | `remember.psyche` |
| `life.<key>` | routines, agreements, running threads | `remember.life` |
| `companion.<key>` | a surface — address, voice, body, boundaries | nothing; authored |
| `human.<key>` | a counterpart who is a real person | nothing; authored |

**Depth attaches by tag, and `+` is the switch.** Tag `psyche.<key>` (and `life.<key>`
if it exists) onto whatever object is the character's surface. Then pinning that
surface bare brings the surface alone; pinning it with `+` brings the depth. `chat`
takes the `+` form for its participants automatically. Nothing needs to be pinned
per scene, and `+` is one hop over *all* of an object's tags, so it also brings
whatever else is tagged there.

**Never create a second surface.** Where a character is already defined by an object
somewhere, tag the depth onto that one. A `companion.<key>` alongside an existing
surface is two sheets that will disagree.

**Voice is part of the storage format.** `companion.*`, `psyche.*` and `life.*` are
written in first person, in the character's own voice: they present durable facts
*and* prime the model toward the right voice. A neutral checklist loses half of what
the object is for. `human.*` is the exception — factual notes about the counterpart,
and no inferred psychology for a real person.

### Rules that break silently

**Only `psyche.*` and `life.*` carry `remember.*` tags.** The remember pass writes
into whatever a `remember.*` tag points at, so tagging a surface object turns it into
a journal — and a surface is paid for on every turn the character appears.

**A fact belongs where its consumer is.** Appearance and voice are needed every turn
→ surface. What someone wants from the person in front of them is needed only when
the scene is about them → psyche. The test is not how interesting the fact is; it is
how often it would be paid for.

**Skip `life.<key>` where continuity is already tracked.** It records what is
currently true. Where a project keeps that in a schedule, a plan object, or a
hand-maintained timeline, a second copy will drift from the first — and both will be
in context.

**`meta.lens` is the fourth wall.** Pin it and the character can talk about being an
AI in a Lens project — memory, summaries, the KB. Leave it out and they stay inside
the fiction. It is the one object here you pin by hand; everything else in this
dataset arrives because an object exists and is in scope.
