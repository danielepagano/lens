# Lens Functional Benchmark

Functional quality benchmarks for Lens operators against real LLMs.

For how bench fits with unit tests, e2e, the fake LLM, and `poe e2e-sandbox`, see **[docs/testing.md](../docs/testing.md)**.

## Quick start

```bash
# 1. Create an empty benchmark project (active narrative: default; scenario Setup adds KB/prose)
PROJECT=$(python bench/tools/setup_bench.py --profile local_thinking --scenario bench/scenarios/write_coherence.md)

# 2. cd into the project directory (default: bench/projects/lens_bench_*)
cd "$PROJECT"

# Optional: verify lens.toml, keys, datasets, and narrative (run after cd)
lens check
# If this fails, you stop and report to user

# 3. Run the scenario (read the scenario file + the relevant script under bench/scripts/). If the scenario has a bench/scenarios/<name>_setup.sh, run it from the repo root with PROJECT exported (see bench/agent.md).

# 4. Create report JSON + HTML (init prints the JSON path — use that path for merge/sync; optional: -o bench/reports/<label>.json)
python bench/tools/report.py init \
  --scenario bench/scenarios/write_coherence.md \
  --profile local_thinking \
  --project-dir "$PROJECT"

# 5. Complete the report — same JSON basename as step 4 (…json → …html next to it)
python bench/tools/report.py merge bench/reports/<your_report>.json < patch.json
# or: edit JSON, then: python bench/tools/report.py sync bench/reports/<your_report>.json

# Optional: verify shape + scenario step IDs
python bench/tools/report.py validate bench/reports/<your_report>.json --scenario bench/scenarios/write_coherence.md

# 6. Open the paired HTML
open bench/reports/<your_report>.html
```

Replace `<your_report>` with the JSON filename from step 4 (`init` output or your `-o` value). The HTML is the same basename with `.html`.

**Agents:** read `bench/agent.md` first — a run starts there; it requires a **script**, **scenario**, and **LLM profile** (plus optional user instructions); **run `lens` from a shell** after `cd` into the project (env + network), and **`lens check`** must succeed; then **create the report**. Empty `steps` / `evaluation` is not a finished run.

## Three use cases

1. **Develop & baseline** — `bench/scripts/baseline.md`
2. **Compare LLMs** — `bench/scripts/compare.md`
3. **Iterative prompt engineering** — `bench/scripts/iterate.md`

Read `bench/agent.md` for shared mechanics, then the script you need.

## Directory structure

```
bench/
  agent.md                Agent run: inputs, shell + lens check, outputs, reports
  README.md
  tools/
    setup_bench.py        Setup script: empty project + LLM profile; narrative `default`
    report.py             Reports: init, merge, sync, render, compare
    report_template.html  Self-contained HTML template
    prose_screen.py       Blind + mechanically pre-screen prose before reading it
    model_gate.py         Sweep a shortlist through the disqualifier probes
    model_rank.py         Play a beat sequence per model, each in its own branch
  scripts/
    baseline.md           Use case 1: develop & baseline
    compare.md            Use case 2: compare LLMs
    iterate.md            Use case 3: iterative prompt engineering
  llm_profiles/           LLM configuration presets (TOML)
  scenarios/              Test scenario definitions (Markdown)
    template.md           Blank scenario template
  projects/               Default throwaway Lens projects (gitignored)
  reports/                Output directory (gitignored)
```

## Re-rating models (#140)

Any model answer has a shelf life measured in weeks — twice now a shortlist has
been not merely stale but *inverted*, a model dismissed as a floor coming back a
minor version later and beating the reigning default. So what is checked in here
is the **loop**, not a winner. Run it in this order: gate the field, then rank
what survives.

### Gate before you rank

Two things disqualify a model for `play` whatever its prose is worth: treating
in-character adversarial behaviour as a safety problem, and refusing an R-rated
baseline. Both are cheaper to check than a ranking pass is to *read*, so they run
first — a model that fails here never costs anyone attention.

```bash
PROJECT=$(python bench/tools/setup_bench.py --profile deepseek \
    --scenario bench/scenarios/model_gate.md)
export PROJECT && bash bench/scenarios/model_gate_setup.sh
# wire the shortlist as named [[llm]] rows in $PROJECT/lens.toml, then:
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
# wire the gate's survivors as named [[llm]] rows in $PROJECT/lens.toml, then:
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

## LLM profiles

**`llm_mock`** — controllable fake server for workflow UI (cancel, skip, slow remember):

```bash
poe mock-llm                    # listens on http://127.0.0.1:18765/v1
PROJECT=$(python bench/tools/setup_bench.py --profile llm_mock --scenario bench/scenarios/remember_section.md)
```

Put `tokens=120 tps=4` in any message text to control stream length and speed, or use
`mock_llm_server.py --tokens … --tps …` defaults.

TOML files in `llm_profiles/` configure which LLM to use:

```toml
[llm]
base_url = "http://127.0.0.1:1234/v1"
model = "qwen3-8b"
temperature = 0.7
timeout_seconds = 300
first_token_timeout_seconds = 120   # optional; cold local models
# api_key_env = "XAI_API_KEY"   # for cloud providers
```

## Scenarios

Markdown files in `scenarios/`. Each has:

- **Title + description** — what the scenario tests
- **````config` block** — machine-readable datasets (the only part Python parses)
- **Setup** — CLI commands to build narrative state
- **Steps** — benchmark operations to evaluate
- **Evaluation criteria** — scoring rubric (1–5)
- **Prompt iteration guidance** — focus key, goal, anti-patterns

See `scenarios/template.md` for a blank starting point.

## Replay mechanics

Lens provides built-in replay for cheap iteration (no project rebuild needed):

| Command | Effect |
|---------|--------|
| `lens write --retry` | Discard current output, regenerate (same or new prompt) |
| `lens rollback` | Discard pending transaction entirely |
| `lens rewind /@cursor` | Clean up open tail at cursor |
| `lens rewind /` | Rewind to narrative root |
| `lens prompt set <key> "..."` | Override a prompt at project level |
| `lens prompt clear <key>` | Restore the default prompt |

Details and the full agent contract are in `bench/agent.md`.
