## Conventions of the `companion` dataset

A companion is not a project. It is a `companion.<name>` object, a
`human.<name>` counterpart, linked `memory.*` objects, and a narrative tree
where chat happens. All of them load together on every exchange, so give each
one a distinct job and do not repeat a fact across two of them.

**Voice is part of the storage format.** `companion.<name>` and its `memory.*`
objects are written in first person, in the companion's own voice: they present
durable facts *and* prime the model toward the right voice. A neutral checklist
loses half of what the object is for. `human.<name>` is the exception — factual
notes about the counterpart, not in the companion's voice.

**Only `memory.*` objects carry `remember.*` tags.** The remember pass writes
into whatever a `remember.*` tag points at, so tagging the companion sheet turns
it into a journal. `remember.psyche` takes slow patterns — temperament, needs,
repair, growth edges — and skips one-off moods. `remember.life` takes concrete
continuity — routines, promises, names, inside jokes — and infers no psychology.
Adding more remember targets slows every summary and tempts the model to write
the same update into all of them.

**`meta.lens` is the fourth wall.** Pin it and the companion can talk about
being an AI in a Lens project — memory, summaries, the KB. Leave it out and they
stay inside the fiction. `meta.companion` is different: it is the runtime
instruction for companion behaviour, and `companion.<name>` links to it.
