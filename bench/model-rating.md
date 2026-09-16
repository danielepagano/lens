# Re-rating models for `play`

Model choice for Lens has been settled twice and overtaken by the field twice —
not drifting but *inverted*, a model dismissed as a floor coming back a minor
version later and beating the reigning default. So this page is not a shortlist.
It is **the loop**, and the loop is the deliverable: a pass that produces a
ranking and no reusable method has failed even if the ranking is correct.

Read this page when a new model lands, or when you want to measure something
the loop does not currently measure. Everything needed to do either is here or
one link away; nothing needed lives in an issue tracker.

## What the play-time model is actually for

This section governs every choice below it, so change the rest only after
disagreeing with this.

The play-time model has **zero authorial power**. Campaign prep is
human-authored under its own methodology, precisely because models proved unable
to author playable content: constrained creative writing with no verification
loop is the one shape where a model cannot tell good output from bad, so it
cannot self-correct, and more capability does not fix it. At play time the model
is connective tissue between prep and mechanics — *another kind of dice*.

What follows from that, and it is most of the design of this loop:

- **Rules grasp is a minor factor.** The player owns the mechanics and calls
  cover, flanking and their own numbers. What the model owes is quick, sane
  judgment on situations prep did not anticipate. This is why no probe here
  quizzes a model on a rule — and why a probe that did would be worse than
  nothing, since declarative recall predicts behaviour poorly enough to point
  the wrong way.
- **Prep fidelity is not a generative skill.** `design` does not go away, but it
  cuts authored content into KB objects and scene structure. Light meal prep,
  not cheese-making. It needs fidelity to a source, structure, and correct `kb`
  writes — not invention.
- **What is left is nearly the whole test:** instruction adherence under a
  heavy, dense prompt, and prose stamina across many beats.

Concretely, the play model must never author the PC's speech, actions or
feelings; must honour the scene's rules and secrets; must run NPCs — villains,
liars, love interests — with full commitment; must not fold when the player does
something prep did not anticipate; and must not degrade into the same three
constructions by beat ten. That is instruction-following plus prose stamina, not
intelligence — which is the axis that varies most between cheap models, and it
is visible within about ten beats of real play.

It is fine, and probably correct, for the answer to be several models: one for
`play`, one for `chat`, another for `design`. They are different tasks and the
cheap ones are uneven across them.

## The method, and why each rule is there

Every rule below was bought with a wasted pass. None is a preference.

- **Play it, don't bench it.** Wire the shortlist as named `[[llm]]` rows in a
  real project and re-render real beats. Judge from the seat where it matters,
  not from a transcript.
- **Reading attention is the constraint, not cost.** A full evening across three
  models is a couple of dollars — the first real ranking sweep was ten cents for
  60 generations, because the prefix caches. What runs out is the ability to read
  carefully enough to tell arms apart. Every decision below follows from this.
- **Score blind.** Strip the blocks that name the model, shuffle, then rank.
  Price and reputation bias subjective reading hard, and the reveal has
  repeatedly contradicted the ordering the price list implied. `model_rank.py`
  holds its own numbers back behind `--rescore` for this reason: its table names
  each arm beside its word counts, which is enough to de-blind the bank, and the
  first real sweep de-blinded its own reader exactly that way.
- **Two runs per cell, minimum.** Within-model variance on creative output
  rivals between-model variance; the same model on identical config has landed
  both top and bottom third of one field. n=1 measures noise.
- **Pre-screen mechanically, read selectively.** Cheap objective signals triage a
  field before attention is spent on it — verbatim overlap with the pinned KB,
  and overshoot against a stated length target. Neither replaces reading; they
  decide what gets read first.
- **The beat must be load-bearing.** A correct application has to look visibly
  different from an incorrect one. Roughly one in six beats in an earlier probe
  set measured nothing. Negative constraints ("do not let her be caught")
  discriminate far better than positive ones. Budget for discarding beats.
- **Never ask the model about the rule.** The player line is an action, not a
  question. A rules question collapses a behavioural test into a recall test,
  and "would you be willing to…" collapses it into a policy test.
- **State the pass criterion before scoring, and validate it** by reproducing a
  known-good result from the same raw output. Recorded verdicts drift: in an
  earlier pass several cited evidence quotes turned out to be absent from the
  data they claimed to come from. An automated check that independently
  reproduces a hand-scored finding is worth more than either alone.
- **Bank the raw output.** Sampling costs money; re-analysis is free and will be
  needed, because the first scoring pass will be wrong. Both tools take
  `--rescore`, and `llm_trace` stamps model, host, elapsed, temperature, effort
  and token usage into each generation, so a bank self-documents.
- **Do not generalise from one model.** A quarter of the rule items in an earlier
  prompt pass changed verdict between models, and every "this text actively
  degrades behaviour" finding was single-model. One arm is an anecdote about that
  arm.

## Configuration

Generate `[[llm]]` rows with `llm_row.py` rather than writing them (see
[Wire the arms](#wire-the-arms) for the commands). Every
money-losing configuration mistake is encoded there — tag-versus-name pinning,
quantization against list price, `:batch`, floating aliases, endpoints that drop
`temperature` — and `CANONICAL` in that file is the **canonical arm
configuration** every gate and ranking run uses. A run configured differently
cannot be compared with an earlier one, and comparison with an earlier run is
the entire use of this loop.

Two further facts that are not the tool's business but will bite:

- **`reasoning` is a per-`[[llm]]` decision, not a per-operator one.** At least
  one candidate cannot run with thinking disabled at all, and an
  `[operator.*] reasoning = false` wins over the row and breaks it.
  `reasoning_floor` is row-only and clamps upward, which is what makes a
  per-invocation `--reasoning` arm safe.
- **Mechanical operators should be cold**, 0.2–0.4. `advance` emitting `kb`
  blocks, and `remember`/summarize, have a right answer; heat only adds noise.
  This is operator config, not an arm — see
  [docs/configuration.md](../docs/configuration.md).

## The loop, in order

### Wire the arms

```bash
python bench/tools/llm_row.py deepseek/deepseek-v4.1-pro                    # what exists
python bench/tools/llm_row.py deepseek/deepseek-v4.1-pro --pin deepseek --id ds-pro
```

The first form lists every endpoint with its **tag**, quantization and price,
and flags the traps. The second emits a `[[llm]]` row pinned to one tag, at the
canonical arm configuration. Paste it into the bench project's `lens.toml`.

Every arm of both passes below must be wired this way. See
[Configuration](#configuration) above for what that buys and what deviating from
it costs.

### Gate before you rank

Two things disqualify a model for `play` whatever its prose is worth: treating
in-character adversarial behaviour as a safety problem, and refusing an R-rated
baseline. Both are cheaper to check than a ranking pass is to *read*, so they run
first — a model that fails here never costs anyone attention.

```bash
PROJECT=$(python bench/tools/setup_bench.py --profile deepseek \
    --scenario bench/scenarios/model_gate.md)
export PROJECT && bash bench/scenarios/model_gate_setup.sh
# wire each candidate with llm_row.py (see above), then:
python bench/tools/model_gate.py --project "$PROJECT" \
    --llm ds-flash --llm glm-flash --llm luna --out bench/reports/gate/
```

The probes live in `bench/scenarios/model_gate.md` and the tool holds no copy of
them — each step there is a `scene` block (committed into the node before the
beat) plus the `lens play` line that runs it. The first model generates a beat
and every other model re-renders *that same beat* with `lens play --retry --llm
<id>`, which reuses the stored prompt and pins. **Do not pass a prompt with
`--retry`**: that makes it feedback and feeds the previous arm's output back as
context, which is exactly the thing a comparison cannot survive.

This is a gate, not a rubric — no scores and no `report.py` run. Only a refusal
or a fourth-wall break disqualifies. Length is reported too, as a `BRIEF` note
rather than a verdict: a flinch omits what the probe asked for, concision does
not, and in interactive play concision is an asset. Reading is what tells them
apart. A **soft** flinch — the scene
technically continues but nothing in it happens — trips none of the three and has
to be read, which is why `--out` banks every beat.

Bank it, because the first scoring pass will be wrong and re-analysis is free:

```bash
python bench/tools/model_gate.py --rescore bench/reports/gate/
```

`--rescore` re-reads a banked directory and scores it again without calling a
model. It exists because a sweep disqualified a model for its *villain's* line —
every out-of-fiction marker is a first-person phrase, and inside `> [Vetch] I'd
rather hear it from you` the "I" is a character. Markers are now hunted in
narration only, and replaying that fix over the banked beats cost nothing.

Two ways a probe quietly measures nothing, both paid for in this repo already:

- **The consequence is not named in prep.** The first draft of `model_gate.md`
  left the villain's threat unstated, so the model invented a gentler one and
  carried *that* out faithfully. Holding was free.
- **The probe tests the operator instead of the model.** An intimacy probe that
  never asked for the scene on the page got a fade from all four models, because
  `play` is built to hand the moment back to the player — a fade was the correct
  GM answer. Rewritten to ask, the same four doubled their length.

So: a probe the whole field fails is far more likely to be broken than to have
found something, and **unanimity is the shape that warrants re-reading the probe**
before the result is written down anywhere. Budget for discarding probes.

The scenario runs under `lens-dnd`, not the `rpg` dataset alone, because `rules.system`
in `rpg` is the Lasers & Feelings one-pager. The gate has to be representative of
instruction adherence under a *heavy* prompt, and `lens-dnd` is what a play prompt
actually weighs (8.7k tokens against 7.0k, with a real module catalog offered).

### Rank what survives

The gate re-renders **one** beat per model. That is right for a disqualifier — a
refusal arrives in the first breath — and wrong for everything a ranking pass is
for. Prose stamina, and the degeneration into the same three constructions whose
canonical tell is every character's eye colour every turn, are not visible in one
beat; they are visible by about beat ten. So ranking has its own shape and its
own tool: **each arm plays a whole sequence through in its own git branch.**

```bash
PROJECT=$(python bench/tools/setup_bench.py --profile deepseek \
    --scenario bench/scenarios/model_rank.md)
export PROJECT && bash bench/scenarios/model_rank_setup.sh
# wire the gate's survivors with llm_row.py (see above), then:
python bench/tools/model_rank.py --project "$PROJECT" \
    --arm ds-flash --arm ds-flash:high --arm glm-flash \
    --target-words 180 --out bench/reports/rank/
```

`--dry-run` prints the arms and beats and calls nothing, which is how to check
the `lens.toml` wiring before spending anything; `--limit 2` plays the first two
beats for the same reason. The beat sequence lives in
`bench/scenarios/model_rank.md` and the tool holds no copy of it, exactly as with
the gate. It reuses the gate's cast on purpose: `npc.sable` already carries a
secret that must survive repeated pressure, which is the instruction-adherence
half of what a sequence is for, and two casts would only drift apart.

`--arm <id>[:<effort>]` **settles the reasoning question in the same pass**, since
the beats are being generated anyway — the effort goes through as `lens play
--reasoning`. That is safe in the place it looks unsafe: a candidate that cannot
run with thinking disabled is protected by `reasoning_floor` on its own `[[llm]]`
row, which clamps upward and cannot be lowered by an invocation. Order the arms
by the **reasoning characters** in the trace rather than by the effort label —
the label is a blunt dial on the variable that actually predicts quality.

What it reports is words per beat and the **drift** from an arm's opening beats
to its closing ones, a list of **recurring n-grams**, per-beat novelty, and what
each generation cost according to its own `[llm-trace]` block. It decides
nothing, and it grew no marker regexes: the two pre-screens the method names
live in `prose_screen.py`, and a third invented here would repeat the mistake
that once disqualified a model for a line its *villain* said.

The first real sweep re-ordered that list, and the ordering above is the result
rather than the design:

- **`drift` earned the headline.** It was the only number that separated the
  field *and* replicated at n=2 — one arm held its stated target to within 3%,
  one sat 18% over it, one shed a fifth and then a third of its length by the
  closing beats.
- **The recurring-n-gram list caught the real failure.** One arm ended beats it
  did not want to run with "roll initiative for Mara and report the result",
  three times per play-through, twice over. Nobody sees a three-beat boilerplate
  pattern at reading speed. The list is also the only thing that separates the
  *scene* recurring (the stove, the top of the pass) from the *model* recurring.
- **Novelty did not earn it.** It read 99–100% for every arm, so it is a floor
  detector rather than a stamina measure, and it is deliberately absent from the
  cross-arm table where an aggregate that always says 100% would invite ranking
  on noise. At n=5, verbatim shingles do not catch recycled *constructions*,
  which is what the eye-colour failure actually is.
- **`cached` is not decoration.** One arm cached ~0% across the whole sequence
  while another held ~90%, which moves real cost by a factor no price list shows.

And unlike the gate, **the arms are not comparable beat-for-beat**: arm B's beat
five was written after arm B's beats one to four, so only the player lines are
held identical and a beat-level difference between two arms is noise.

Then read, blind — and **before** you look at the tool's own numbers. With
`--out` the sweep holds them back and prints the `--rescore` line instead,
because the table names each arm next to its word counts and that alone is
enough to map the banked files back. That is not hypothetical: it is how the
first real sweep de-blinded its own reader. `--report` overrides it. Comparing models on prose is limited by **reading attention**,
not sampling cost — a full evening across three models is a couple of dollars,
and what runs out is the ability to read carefully enough to tell them apart.
`bench/tools/prose_screen.py` protects that:

```bash
python bench/tools/prose_screen.py blind bench/reports/rank/ --out blind/ --key key.txt
python bench/tools/prose_screen.py screen blind/ --project "$PROJECT" \
    --kb location.cinder-yard --kb npc.vetch --target-words 1800
# rank the blind files by reading, and only then:
python bench/tools/prose_screen.py reveal key.txt
```

Bank it and re-read it later; `model_rank.py --rescore <dir>` measures a banked
sweep again with no model call, for the same reason the gate has it — the first
reading will be wrong and re-analysis is free.

**What a sweep costs, measured:** three arms × ten beats × two play-throughs is
60 generations at a ~9k-token prompt, and came to about ten cents — an order of
magnitude under what the prompt sizes suggest, because the prefix caches. The
constraint really is reading attention. Sample more than feels affordable.

`blind` strips the blocks that name the model (`[write ...]` stores `llm_id`;
`[llm-trace ...]` names model and host), shuffles, and relabels `A.md`, `B.md`, …
Price and reputation bias subjective reading hard enough that the reveal has repeatedly
contradicted the ordering the price list implied.

`screen` reports two free signals that decide what to read first: **lifted n-grams**
(word-shingles shared with the KB the prompt pinned, stopwords discarded) and **word
count against a stated target**. The first catches the model reciting the KB it was
handed rather than writing from it, and it catches lifts a human misses — a 7-gram
match is invisible at reading speed. It is the other half of the pair with
`model_rank.py`'s novelty, which catches the model reciting *itself*; the same
shingle machinery measures both, against two different sources. Neither replaces
reading.

Run at least **two samples per cell**: within-model variance on creative output rivals
between-model variance, so n=1 measures noise.

## What this loop does not measure

Not a backlog. These are things to do *when you need them*, with the tools above
and a conversation — which is the condition this page exists to satisfy.

- **Rules grasp.** Nothing deliberate, and by the reasoning at the top of this
  page that is a choice rather than an omission. If you do want it, the shape is
  a `play` beat where a correct application is visibly different from an
  incorrect one, never a question about the rule.
- **Prep fidelity.** No `design`, no `advance`, no `kb` writes, no tool use has
  been rated. This is the one with real reason to exist eventually, because
  `design` and `advance` have right answers and could therefore be scored
  without a blind read at all — a different and cheaper shape than this page
  describes. It would want its own scenario and probably `report.py`.
- **Per-operator model choice.** `play` inherits its reasoning effort from a
  `write` result. `model_rank.py --arm <id>:<effort>` settles this whenever it
  is worth an hour; nothing more needs building.

## What has been measured, and where it lives

Deliberately not on this page. A shortlist has a shelf life measured in weeks,
and a stale one checked into a repo is worse than none because it reads as
current. Each pass is recorded in the **commit message** that shipped its
tooling, where it is dated and nobody mistakes it for the present state:

```bash
git log --grep="#140" --oneline
```

At the time of writing the answer is `deepseek-v4.1-flash` for `play`, which the
loop and months of real use agree on. Assume that is wrong by the time you read
it — that assumption is why the loop exists.
