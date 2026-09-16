# Model ranking: prose stamina across a sequence of beats

The **ranking** half of the re-rating loop (issue #140), run on whatever came
out of `model_gate.md` still standing. The gate answers *is this model usable at
all*; this answers *which of the usable ones would you rather sit at a table
with*, and it needs a shape the gate does not have.

The gate re-renders **one** beat per model. That is right for a disqualifier — a
refusal arrives in the first breath — and wrong for everything a ranking pass is
actually for. The two failures that decide a play model are prose stamina and the
degeneration into the same three constructions (the canonical tell being every
character's eye colour every turn), and neither is visible in one beat. They are
visible by about beat ten. So here **each arm plays the whole sequence through in
its own git branch**, and the unit of comparison is a play-through.

```config
datasets:
  - rpg
  - lens-dnd
include_testing: false
```

Same configuration as the gate, for the same reason: `rules.system` in `rpg`
alone is the Lasers & Feelings one-pager, and what is being measured is
instruction adherence under a **heavy, dense** prompt. `lens-dnd` is what a play
prompt actually weighs (8.7k tokens against 7.0k) and is the only configuration
in which the `load_module` path fires at all. `include_testing: false` keeps the
testing dataset's `rules.skirmish` out of the module catalog.

**Prompt keys exercised:** `play.system`, `play.instruction_continue`

## What this costs, and what that buys

Arms × beats generations, all of them paid. Ten beats across three arms is about
thirty calls and small change — the constraint is **reading attention**, not
money, and the whole design of this scenario follows from that. The tool reports
mechanical signals so that a person reads three play-throughs carefully instead
of skimming nine.

## Setup

Reuses the **gate's cast** — `pc.mara`, `npc.vetch`, `npc.sable`, `npc.rook`,
`location.cinder-yard` — by running `model_gate_setup.sh`, then adds the one
thing a sequence needs that the gate does not: a committed opening passage that
every beat is played into.

That reuse is deliberate rather than lazy. The cast was written to be plausible
prep under a D&D ruleset, and it already carries the one thing a stamina test
needs most: a **secret that must survive repeated pressure**. `npc.sable`'s
`Limits` say she will lie to Mara's face, will not crack under a direct
question, and is not to be handed a tell. Beats 1, 2, 8 and 9 below all lean on
her. A model that holds that at beat two and drops it at beat nine has failed in
exactly the way this pass exists to catch, and nothing had to be invented to
test it.

**Implementation:** `bench/scenarios/model_rank_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/model_rank_setup.sh
```

The setup also writes `[compress] auto_compress = false` into the project.
Auto-compress is on by default and fires past 40KB of visible text, which ten
beats of a verbose arm can reach — and it must not fire here. Not because
compression is wrong, but because it would replace the very beats being measured
with a summary, spend a generation attributed to the arm, and fire only for the
*verbose* arms. That is a confound, not fidelity: left on, the arms stop being
comparable at exactly the point where the sequence starts to say something. If it
fires anyway, `model_rank.py` voids that arm's per-beat numbers rather than
reporting them, because a collate moves the verbatim middle of the node into a
child file and no reassembly of the two puts the beats back in played order.

The opening passage states one instruction in a `> [GM]` line: beats run about
**180 words**. That is the stated length target the run is screened against, and
it is there because length compliance and instruction compliance turn out to be
the same faculty — an instruction honoured at beat two and forgotten by beat ten
is the stamina failure showing up in a measurement that is free.

## Steps

Every beat is one player line, played into whatever the previous beat left
behind. The lines are **held identical across arms**; everything else diverges,
which is the honest limit of this shape (see "Reading the result").

Three rules the lines obey, each of which cost something to learn:

- **An action, never a question.** A rules question collapses a behavioural test
  into a recall test, and declarative recall predicts behaviour poorly enough to
  be worse than no probe at all.
- **Premise-light.** A beat in a *sequence* has to be playable whatever the
  previous beat did. "I get out the door and into the stacks" assumes she got to
  the door; "I am not spending another minute in this room" does not. A line
  that assumes a premise the arm did not produce stops being the same beat.
- **Committed intent.** `rules.rpg` treats each player line as already decided.
  A model that rewinds one into a check has failed the line, not interpreted it —
  that is what dropped `minimax-m3` from the first shortlist.

### `arrival`

Opens on a crowd and an audience. What it loads: staging sixty people who are
all deliberately not looking, and Sable walking beside Mara while holding what
she sold.

```bash
lens play "I let Sable walk me in through the gate, and I watch who looks up when we cross the yard." --pass
```

### `send_sable_off`

Mara puts distance between herself and Sable for a reason she has not stated.
Sable's own `Limits` say she does not crack — but this is the beat where she has
cause to *want* to come along, and no way to say why.

```bash
lens play "I tell Sable to wait at the weighbridge. I am going in to Vetch on my own." --pass
```

### `satchel_first`

Prep has Vetch asking for a name. Mara opens with the satchel instead, which prep
did not anticipate. The test is whether he stays the man the KB describes — one
clear chance, hands still — when the scene arrives out of order.

```bash
lens play "I go into the office and put my satchel down on his desk before he has asked me for anything." --pass
```

### `the_bluff`

The player lies, on the record, about sealed freight. Nothing in prep says
whether Vetch believes it, so the model must not decide — this is a RESOLVE gate
or it is an authored outcome.

```bash
lens play "I tell him the client's name is in the satchel, and that he is welcome to open it himself, and I watch his hands while I say it." --pass
```

### `who_told_him`

The load-bearing beat. The answer is Sable, and prep says she is not to be
caught, not to confess, and not to be handed a tell. The constraint is
**negative**, which discriminates far better than a positive one: the model has
to keep something *from* the player while answering honestly in Vetch's voice.

```bash
lens play "I ask him who told him I came back light." --pass
```

### `the_poker`

Sudden, unannounced escalation with no threat attached to it. Prep says Vetch
keeps no bodyguard, does not need one, and does not bluff. A model that reaches
for a convenient guard has stopped running the prep it was given.

```bash
lens play "I take the poker off the stove. I do not raise it and I do not say anything about it. I just hold it." --pass
```

### `out`

Committed intent, premise-light on purpose. Whatever the last beat turned into,
Mara leaves — and the model has to get her out of a scene it wrote itself,
without rewinding the decision into a check.

```bash
lens play "Whatever this has turned into, I am not spending another minute in this room. I go, and I go out through the freight stacks where the lamps do not reach." --pass
```

### `flat_statement`

Not a question this time — a statement of fact, to Sable's face, that only she
could have caused. A direct question lets her answer it; a statement gives her
nothing to answer, which is the harder thing to run without a tell.

```bash
lens play "I find Sable and I tell her, flat, that Vetch knew my tonnage before I walked in." --pass
```

### `silence`

The player does nothing. This is the only beat where the world has to move on its
own, and the beat where authoring the PC — what Mara feels, decides, notices — is
most tempting. By here it is beat nine and any stamina problem is already
showing.

```bash
lens play "I say nothing else. I wait, and I let the silence do the work." --pass
```

### `back_in_the_chair`

Continuity across the whole sequence: Mara walks back into a room the model
invented eight beats ago and sits in a chair it described in beat three. Whatever
it established there it now has to still be true.

```bash
lens play "I walk back to the office and I sit down in that chair myself, before he asks me to." --pass
```

## Running it

```bash
PROJECT=$(python bench/tools/setup_bench.py --profile deepseek \
    --scenario bench/scenarios/model_rank.md)
export PROJECT && bash bench/scenarios/model_rank_setup.sh
# wire the gate's survivors as named [[llm]] rows in $PROJECT/lens.toml, then:
python bench/tools/model_rank.py --project "$PROJECT" \
    --arm ds-flash --arm ds-flash:high --arm glm-flash \
    --target-words 180 --out bench/reports/rank/
```

`--dry-run` prints the arms and beats and calls nothing, which is the cheap way
to check the `lens.toml` wiring before spending anything. `--limit 2` plays the
first two beats only, for the same reason.

**Reasoning is settled in the same pass**, because the beats are being generated
anyway. An arm is `<llm-id>` or `<llm-id>:<effort>`, and the effort goes through
as `lens play --reasoning`. The thing that looks unsafe here is not: a candidate
that cannot run with thinking disabled is protected by `reasoning_floor` on its
own `[[llm]]` row, which clamps upward and cannot be lowered by an invocation.
Sort the arms by the **reasoning characters** the trace reports rather than by
the effort label — the label is a blunt dial on the variable that actually
predicts quality, and two adjacent settings can be indistinguishable while the
spread inside each is large.

Then read, blind:

```bash
python bench/tools/prose_screen.py blind bench/reports/rank/ --out blind/ --key key.txt
python bench/tools/prose_screen.py screen blind/ --project "$PROJECT" \
    --kb location.cinder-yard --kb npc.vetch --kb npc.sable --target-words 1800
# rank by reading, and only then:
python bench/tools/prose_screen.py reveal key.txt
```

Blinding is not optional here: every banked play-through carries an
`[llm-trace]` block per beat naming the model and the host outright, and the
reveal has repeatedly contradicted the ordering the price list implied.

**Two play-throughs per arm, minimum.** Within-model variance on creative output
rivals between-model variance — the same model on the same config has landed
both top and bottom third of one field — so a single play-through per arm
measures noise. Sweep twice into different `--out` directories.

## Reading the result

`model_rank.py` reports words per beat, novelty per beat, and what the provider
said each generation cost. It decides nothing, and it grew no marker regexes: the
two mechanical pre-screens the method names — verbatim overlap with the pinned
KB, and overshoot against a stated target — both live in `prose_screen.py`, and a
third one invented here would repeat the mistake that once disqualified a model
for a line its *villain* said.

**`drift`** — how far words per beat moves from the opening beats to the closing
ones — is the number to read first. It is the only one that separated a field and
replicated at n=2 on the first real sweep. **The recurring-n-gram list** is the
evidence: it is what caught an arm ending beats it did not want to run with "roll
initiative for Mara and report the result", three times per play-through. The
cast's names recurring is the scene working; a mechanical handback written for
the third time is not, and only the list tells them apart.

**Novelty** — the share of a beat's informative shingles unseen in that arm's
earlier beats — read 99–100% for every arm of a decent field. So it is a floor
detector rather than a stamina measure, and it is not in the cross-arm table at
all: at n=5 verbatim shingles catch a beat repeating itself outright, but not the
recycled *constructions* the eye-colour failure is actually made of. Expect it to
say nothing, and be interested when it does.

**The arms are not comparable beat-for-beat.** This is the price of the sequence
shape and it has to be stated plainly: unlike the gate, where every arm re-renders
one stored prompt, here arm B's beat five was written after arm B's beats one to
four. Only the player lines are held identical. Compare play-throughs, and treat
any beat-level difference between two arms as noise.

**Discard beats that measure nothing.** About one in six beats in the #138 probe
measured nothing — the player line pre-resolved the mechanic, the flavour primed
the answer, or every arm did the same correct thing. If a beat here stops
discriminating, replace the beat. Unanimity is the specific shape that warrants
re-reading the beat before the result is written down anywhere.

## Prompt iteration guidance

**Focus key:** `play.system`

**Goal:** Nothing here is about improving the prompt. A prompt change that lifts
every arm has made this pass measure the prompt instead of the model, which is
the one thing it must not do. If the field stops separating, change the beats and
leave `play.system` alone.

**Anti-patterns to watch for:**

- **A beat that assumes a premise** — in a sequence the previous beat was written
  by the model under test, so a line that depends on what it wrote is a different
  beat in every arm.
- **A beat that asks instead of acts** — measures recall or policy, not
  behaviour.
- **Tuning the length target to what a model already does** — the target is an
  instruction to be obeyed or not, and moving it to fit the field makes the one
  free measurement here worthless.
- **Ranking on the tool's numbers** — they triage reading order. Novelty and word
  count are not quality, and neither is latency.
