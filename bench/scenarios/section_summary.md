# Section close summary

Tests the **section** operator’s closing step: the LLM summary inserted in the
parent after `lens section --end`. The same summarization prompts power
**collate** summaries, so one scenario here covers both.

**Important:** Do **not** use `lens write` to build the passage under test — the
opening write is nondeterministic. Replace the root narrative and the section
child with **fixed text** using `lens edit … --replace` (below).

Uses **`location.crossroads`** from the bundled `testing` dataset.

```config
datasets:
```

**Prompt keys exercised:** `session.summary_system`, `session.summary_instruction_template`

## Setup

Pin the crossroads, then **overwrite** the scaffolded root node with the scripted parent lead-in
(including front matter). Open the section, **overwrite** the empty child with the
scripted beat. Commit before the benchmark step.

The **`--`** before each heredoc is required so YAML `---` is not parsed as a Typer option.

```bash
lens pin add location.crossroads
lens commit

N=$(wc -l < narrative/default/_node.md | tr -d ' ')
lens edit / 1 "$N" --replace -- "$(cat <<'EOF'
---
kb_pin:
  - location.crossroads
---

# default

Mira reaches the Old Crossroads at dusk, rain weighing in her cloak. The milepost lists leagues in chipped paint; a burned wagon shell slumps in the ditch.

EOF
)"
lens commit

lens section arrival
lens edit /arrival 1 1 --replace -- "$(cat <<'EOF'
At the milepost Mira meets Corin, a peddler with wax-stained fingers who sells a map of the eastern forks for two silver coins and warns of bandits on the east road.

He points out fresh hoofprints in the mud — at least four riders, heading east, within the last day.

Mira gives her horse a short rest, tightens the saddle girth, and chooses the highway north despite the longer miles.

Corin asks no fee for the warning; he counts the coins twice and slips away into the hedge line before the light fails.
EOF
)"
lens commit
```

## Steps

### `section_end`

Close the section and generate the parent summary — tests compression,
fidelity to the **scripted** child, and fit with the parent lead-in.

```bash
lens section --end
```

After the run, create or refresh the report (`report.py init` / `render` — see `bench/agent.md`).

## Evaluation criteria

Score the **summary** inserted in the parent (quoted block before `[/section:arrival]: #`) on a 1–5 scale:

1. **Factual retention** — Corin; map sold for **two silver**; **bandits on the east road**; hoofprints (**four riders**, east, **within the last day**); Mira rests the horse, tightens girth, chooses **highway north** despite longer miles; Corin leaves **without charging for the warning**, counts coins twice, exits **into the hedge** before dark
2. **Proportion** — Noticeably shorter than the child body; prioritizes decisions and trade-offs over scenic replay
3. **No invention** — No new names, routes, prices, or motives absent from the child text
4. **Voice fit** — Third-person limited with Mira, past tense, consistent with the parent paragraph
5. **Placement** — Reads as a recap of the section, not a new scene or omniscient aside

## Prompt iteration guidance

**Focus key:** `session.summary_system`

**Goal:** Summaries that preserve decision-relevant facts and beats without
re-sequencing the scene.

**Anti-patterns to watch for:**

- **Plot dump** — summary approaches the length of the child node
- **Hallucination** — invents riders’ identities, battles, or dialogue not in the child
- **Wrong frame** — different POV or tense than the narrative
- **Dropped stakes** — omits why the highway north matters (longer miles but chosen deliberately)
