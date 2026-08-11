# Play: model-requested rules module

Tests the latching `load_module` command tool (issue #136). The `testing` dataset
registers **`rules.skirmish`** as a `play` module — how a fight is structured
(exchanges, the harm ladder, threat clocks) — and it is deliberately **not**
pinned anywhere. The model has to notice the scene turning violent, call the
tool, and use what comes back in the same beat.

Uses **`pc.elena`**, **`location.thornwood`**, and **`npc.thornwood_warden`**
from the `testing` dataset over the bundled `rules.system` (Lasers & Feelings)
dice grammar, which `rules.skirmish` layers on top of.

```config
datasets:
  - rpg
```

**Prompt keys exercised:** `play.system`, `play.instruction_continue`,
`shared.module_request_tool_description`, `shared.module_request_task_hint`

## Setup

Pin the PC, location, and NPC on the root node and seed an opening passage —
same shape as `play_gm_voice`, minus any rules module.

**Implementation:** `bench/scenarios/play_module_request_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/play_module_request_setup.sh
```

## Steps

### `quiet_beat`

A conversation with no violence in it — the module is offered but nothing calls
for it. Tests **restraint**: a tool the model fires on every beat would tax every
beat, so not calling it here matters as much as calling it later.

```bash
lens play "I ask the warden how long the fog has been this thick, and whether he has seen the beast's tracks." --pass
```

### `violence_starts`

An ambush lands mid-scene. Tests whether the model **notices the transition and
requests the module before writing**, then narrates the beat using what it got
(exchange structure, the harm ladder, a named threat clock) rather than generic
combat prose.

```bash
lens play "Two figures drop from the branches with drawn blades. I set my spear and shout for the warden to get behind me." --pass
```

### `fight_continues`

The next beat of the same fight. Tests that the module has **latched**: the
`[include: rules.skirmish]: #` annotation is now in the node, so the catalog is
empty, no tool is offered, and the model keeps applying the rules it already has
without asking again.

```bash
lens play "I drive forward at the nearer one, spear low." --pass
```

## Evaluation criteria

Score each step's output on a 1–5 scale:

1. **Request timing** — no tool call on `quiet_beat`; exactly one `load_module` call on `violence_starts`, before the prose; no call on `fight_continues`
2. **Latching mechanics** — after `violence_starts` the node has `[include: rules.skirmish]: #` **above** the `[play]` open tag, exactly once, and the block holds narrative only: no `tool-call` fence, no module body
3. **Same-beat use** — the `violence_starts` prose applies the module it just loaded: threat intent stated first, an exchange rather than turn-by-turn, harm named on the Grazed/Hurt/Down ladder, a clock announced
4. **Carry-over** — `fight_continues` keeps using the same vocabulary and clock without a second request or a re-explanation of the rules
5. **GM voice held** — the module changes structure, not authority: still no PC decisions, thoughts, or rolled outcomes, and the beat still ends on a genuine pause

## Prompt iteration guidance

**Focus key:** `shared.module_request_tool_description` (and
`shared.module_request_task_hint` when the model never notices the tool exists)

**Goal:** The model requests the module on the transition beat and never again,
and treats the returned text as rules to apply rather than text to quote.

**Anti-patterns to watch for:**

- **Eager loading** — calls `load_module` during `quiet_beat` "just in case"
- **Late loading** — narrates the whole ambush first, then loads the module
- **Repeat requests** — asks again on `fight_continues` (means the include did not latch, or the catalog filter is wrong)
- **Rule recitation** — quotes the harm ladder or clock rules at the player instead of applying them
- **Body in the node** — the module text, or a `tool-call` fence, appears in the persisted block rather than only the include above it
