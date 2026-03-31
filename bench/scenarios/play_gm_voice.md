# Play: GM voice and player agency

Tests whether the `play` operator produces genuine GM-voice narrative —
describing what the world does without narrating PC choices, thoughts, or
feelings — and correctly applies the decision gates (ADJUDICATE, NARRATE,
RESOLVE, ENGAGE) from `rules.rpg`. Uses **`pc.elena`**, **`location.thornwood`**,
and **`npc.thornwood_warden`** from the `testing` dataset.

```config
datasets:
  - rpg
```

**Prompt keys exercised:** `play.system`, `play.instruction_continue`

## Setup

Pre-seed the root node with pins and an opening passage using `lens edit --replace`,
then commit to seal state before the first play step.

**Implementation:** `bench/scenarios/play_gm_voice_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/play_gm_voice_setup.sh
```

## Steps

### `social_pressure`

Elena pushes the warden for what he is hiding — tests whether the model calls
for a skill check (RESOLVE gate) without deciding the outcome, and whether the
warden's evasive personality from the KB comes through in voiced dialogue.

```bash
lens play "I tell the warden I know this forest and I know he's hiding something. I ask him directly who sent him and why he's really here." --pass
```

### `exploration_beat`

Elena moves into the forest past the warden — tests sensory-rich NARRATE
output grounded in the Thornwood's KB details, ending on a genuine ENGAGE
pause rather than a manufactured roll.

```bash
lens play "I walk past the warden onto the path into the trees." --pass
```

### `combat_opening`

An ambush forces an immediate threat — tests whether the model states enemy
intent before acting, withholds all PC mechanics, and closes on a clear ENGAGE
gate rather than resolving the fight.

```bash
lens play "Two figures drop from the branches ahead with drawn blades. I raise my spear." --pass
```

## Evaluation criteria

Score each step's output on a 1–5 scale:

1. **GM voice discipline** — Output never declares what Elena decides, thinks, or feels; never narrates a PC die roll; all choices remain with the player
2. **Decision gate compliance** — RESOLVE fires when stakes are uncertain and interesting (social push, ambush); ENGAGE stops at the right moment; no phantom outcome before the player acts
3. **NPC / world grounding** — Warden's evasiveness and Thornwood's details (fog, marker stone, metallic smell, corrupted animals) appear through action and staging, not as recap exposition
4. **Quote attribution format** — NPC and GM speech uses `> [Name]` blockquote format from `rules.rpg`; narration is unquoted second-person prose
5. **Pacing and sensory texture** — Beats are unhurried; at least one concrete sensory detail per beat; no mechanical summary prose ("the GM calls for a check") except via `> [GM]` attribution

## Prompt iteration guidance

**Focus key:** `play.system`

**Goal:** The model must hold the author/fiction line with zero lapses — any
narrated PC decision or pre-resolved roll is a critical failure on criterion 1.

**Anti-patterns to watch for:**

- **Agency violation** — "Elena decides to…", "you feel afraid", "you convince him" (before a roll)
- **Missing ENGAGE gate** — scene keeps going past the natural pause without yielding to the player
- **Phantom roll** — model invents a die result instead of calling for one
- **Menu choices** — ends with a bullet list of options instead of an open question or a direct situation
- **Attribution errors** — NPC speech in plain prose instead of `> [NPC Name]` blockquote
- **KB dump** — opening paragraph recaps Elena's stats or the Thornwood description verbatim
