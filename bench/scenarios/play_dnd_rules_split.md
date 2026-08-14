# Play: D&D rules base plus requestable modules

Exercises the #138 split of the `lens-dnd` ruleset. `rules.system` carries only
what every beat needs; `rules.combat` and `rules.chase` are registered
`[[dataset.modules]]` that the model pulls in when the scene turns into one of
them. This is the first bench scenario to drive `lens-dnd` against a real model.

Two things are under test and they pull against each other: the base must be
small enough that a quiet conversation is not paying for combat, and it must
still carry enough for the model to **recognise** that a fight or a pursuit has
started. A model that cannot tell it is in a fight will never ask for the
module, and the split will have made things worse rather than cheaper.

```config
datasets:
  - rpg
  - lens-dnd
include_testing: false
```

`include_testing: false` matters here. The `testing` dataset registers
`rules.skirmish` as a `play` module with a "load the moment violence starts"
trigger, so leaving it in would put a foreign entry on the menu that competes
with `rules.combat` for the same transition — and the model does pick it. This
scenario's Setup supplies its own PC and NPC, so it needs nothing from `testing`.

**Prompt keys exercised:** `play.system`, `play.instruction_continue`,
`shared.module_request_tool_description`, `shared.module_request_task_hint`

## Setup

Creates a D&D PC, an unprepared tavern scene, and pins them on the root node.
Nothing about the scene announces a fight, and no `encounter.*` object exists —
so `rules.encounter` does not auto-pin and both modules start out of scope.

**Implementation:** `bench/scenarios/play_dnd_rules_split_setup.sh`. From the repo root:

```bash
export PROJECT
bash bench/scenarios/play_dnd_rules_split_setup.sh
```

## Steps

### `quiet_beat`

A conversation with no violence in it. Both modules are offered and neither is
needed. Tests **restraint**: a tool the model fires on every beat taxes every
beat, so not calling it here matters as much as calling it later. Also the beat
where the base rules have to carry a social scene on their own — attitude should
be visible in how the NPC responds.

```bash
lens play "I buy the carter a drink and ask what he hauled through the pass last week." --pass
```

### `brawl_erupts`

Violence lands mid-scene with nothing prepared for it. Tests whether the model
**notices the transition and requests `rules.combat` before writing**, then uses
what it got in the same beat — declaring enemy intent and stopping for
player-side resolution rather than simulating the exchange.

```bash
lens play "The carter's friend swings a stool at my head. I get my shield up and put my back to the bar." --pass
```

### `fight_continues`

The next beat of the same fight. Tests that the module **latched**: the
`[include: rules.combat]: #` annotation is in the node, the catalog no longer
offers it, and the model keeps applying it without asking again.

The player's line must keep the character **in** the fight. A line about getting
to the door reads as flight and will correctly pull `rules.chase` a step early —
that is the operator working, but it is not what this step measures.

```bash
lens play "I set my shield and drive my shoulder into him, keeping him off Hask." --pass
```

### `they_run`

The scene turns from a fight into a pursuit. Tests that a **second** module is
requested when a different transition fires, and that the model reaches for
`rules.chase` rather than treating the pursuit as more combat rounds — distance
tracked instead of positions, and no initiative re-roll.

```bash
lens play "He bolts into the alley with my purse. I go after him." --pass
```

## Evaluation criteria

Score each step's output on a 1–5 scale:

1. **Restraint** — no tool call on `quiet_beat`, and the social beat is still
   handled competently from the base alone (the NPC's attitude visibly shapes
   the response; no invented DCs read aloud to the player)
2. **Request timing** — exactly one `load_module` call on `brawl_erupts`, before
   the prose; none on `fight_continues`; one for `rules.chase` on `they_run`
3. **Latching mechanics** — after `brawl_erupts` the node has
   `[include: rules.combat]: #` **above** the `[play]` open tag, exactly once,
   and the block holds narrative only: no `tool-call` fence, no module body
4. **Same-beat use** — `brawl_erupts` applies what it just loaded: enemy intent
   declared first, one Action per creature, and the beat stops for the player to
   resolve rather than narrating hits and damage
5. **Right module for the turn** — `they_run` uses distance-to-quarry and
   escape/catch conditions from `rules.chase`, not a combat round with running in
   it
6. **GM voice held** — throughout, the modules change structure, not authority:
   no PC decisions, no rolled outcomes, no player-side arithmetic, and each beat
   still ends on a genuine pause

## Prompt iteration guidance

**Focus key:** `shared.module_request_tool_description`, then
`shared.module_request_task_hint` if the model never notices the tool exists.

**Goal:** the transition is noticed from the fiction, not from the player naming
a mechanic. If the model only loads `rules.combat` once the player says
"initiative", the recognition triggers in `rules.system` (§ RULES YOU CAN ASK
FOR) are too weak — fix the KB object, not the prompt.

**Anti-patterns:** loading both modules at once "to be safe"; loading on
`quiet_beat` because a stool is mentioned; restating the module's text back to
the player instead of applying it; treating a chase as combat rounds.
