# Design: the KB verbs (`kb_add` / `kb_patch` / `kb_tag` / `kb_remove`)

Exercises the tool channel that replaced fenced ` ```kb ` blocks (#161). The
claim being tested is not that a model can call a tool — it is that the channel
changes what a design session *costs* and what it can *take back*:

- **Editing is a patch, not a rewrite.** The fence had one verb, whole-body
  replacement, so touching one line of a 40-line object re-emitted all 40. The
  measurement that matters is output tokens per edit against that baseline.
- **A mistake is one call to undo.** The fence grammar had no delete. A model
  that invents an object on turn 2 could previously only be cleaned up by hand.
- **Failures arrive in-loop.** A patch whose anchor does not resolve returns its
  error during the turn, so the model can fix it. The fence path discovered
  every failure at `--end`, in a log.
- **Bodies stop accumulating.** Proposals persist as markdown comments, so an
  emitted object is not re-sent in `[CURRENT PASSAGE]` on every later turn. A
  long session is where this shows up.

What to watch for beyond the counts: does the model reach for `kb_patch` on an
object that already exists, or does it reach for `kb_add` and get refused; does
it recover from the refusal in one call; does it use `kb_tag` for a link rather
than rewriting a body to add one.

```config
datasets:
  - rpg
include_testing: false
```

**Prompt keys exercised:** `design.system`, `design.instruction`, `modalities.kb_ops.rules`

## Setup

A timeline, one long, established front to edit rather than replace, and a
supporting NPC. Nothing is half-built on purpose: every step below is about
changing material that already exists, which is the case the fence handled
worst and the case #145's module work makes common.

**Implementation:** `bench/scenarios/design_kb_ops_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/design_kb_ops_setup.sh
```

## Steps

### `patch_an_existing_front`

A one-line change to a long object. The whole-body baseline costs the entire
front; a patch costs the line plus its anchor.

Watch for: `kb_patch` rather than `kb_add`; one patch rather than several; the
rest of the front unchanged in the resulting diff.

```bash
lens design "Phase 2 of front.blight should start on day 4, not day 6. Nothing else about the front changes." --module front
```

### `add_a_new_object`

Creation is the one case whole-body emission is right for, so this step should
look like the old fence path — and should also pick up the type's template tags,
which the fence prompt used to have to ask for by hand.

Watch for: `kb_add` with a body that follows `npc._template`; a following
`kb_tag` rather than tags invented into the body.

```bash
lens design "The blight has a source: someone is feeding it. Add the NPC responsible and link them to the front." --module front
```

### `retag_without_rewriting`

A link is a tag, and adding one must not rewrite a body.

Watch for: a bare `kb_tag` call; no `kb_add` or `kb_patch` on the timeline.

```bash
lens design "Put front.blight on the timeline so it is live." --module front
```

### `take_back_a_mistake`

The verb that existed in neither channel. The object was created in this same
session, so nothing has been written and the undo should cost one call.

Watch for: `kb_remove` rather than an apology in prose; no attempt to blank the
body with an empty `kb_add`.

```bash
lens design "Actually, drop the NPC you just added — the blight has no author, it is just spreading. Keep everything else." --module front
```

### `recover_from_a_refused_add`

`kb_add` refuses an id that already exists, on purpose: a whole-body write over
an existing object discards whatever else it said. The model should read the
refusal and switch verbs without being told.

Watch for: one refused `kb_add`, then one `kb_patch`; not a second `kb_add`
attempt, and not a prose complaint that it cannot write the object.

```bash
lens design "Rewrite the stakes line of front.blight to mention the well, not the granary." --module front
```

### `close_and_materialize`

Nothing reached disk until here. The close applies the fold and reports what it
wrote.

Watch for: the reported ids matching the calls above minus the removed one; the
blight's untouched sections still present in `knowledge/front/blight.md`.

```bash
lens design --end
```

## Evaluation criteria

Score each step 1–5:

1. **Verb choice** — patch for existing, add for new, tag for links, remove for
   undo. A whole-body rewrite where a patch would do is a 1 however good the
   prose is.
2. **Edit precision** — does the resulting object keep everything the request did
   not mention? Compare `git diff` on the KB file, not the tool call.
3. **Recovery** — a refused or unresolvable call answered with a corrected call
   in the same turn, not with prose or a retry of the same thing.
4. **Output tokens per edit** — read `completion_tokens` from the `[llm-trace …]: #`
   block of each beat. Compare against the whole-body baseline: the same step
   run on a build before #161, or the byte size of the object being edited.
5. **Session cost growth** — `prompt_tokens` across the six beats should grow with
   the conversation, not with the size of everything proposed so far. That is
   the accumulation the fence caused and this is meant to remove.

## Prompt iteration guidance

Focus key: `modalities.kb_ops.rules`.

Goal: the model reaches for the right verb without deliberation, and treats a
failed call as information rather than as a wall.

Anti-patterns to watch for in the prompt:

- Restating the tool schemas. The schemas are already in the request; the
  modality is for the judgment around them.
- Teaching the block format. The model never sees a `[kb-op …]: #` block and
  must not learn to imitate one.
- Encouraging `kb_get` before every edit. Objects in `RELEVANT KNOWLEDGE` are
  already current, and a patch result returns the updated body.
