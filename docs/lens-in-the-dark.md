# Lens in the Dark

A lightweight RPG system for Lens, based on [Blades in the Dark](https://bladesinthedark.com/) by John Harper. Used under the [Creative Commons Attribution 3.0 Unported license](https://creativecommons.org/licenses/by/3.0/). This is a [Forged in the Dark](https://bladesinthedark.com/licensing) game.

Lens in the Dark (LitD) is a setting-neutral system designed to work with Lens's AI operators. It strips Blades in the Dark down to its essential mechanics — position, effect, stress, clocks — and removes the heist-specific scaffolding (heat, wanted level, claims, entanglements, score structure) in favor of Lens's own tools for world progression.

## How It Works with Lens

The AI (via `play`) is your GM. It sets scenes, voices NPCs, sets position and effect for your rolls, narrates consequences, and keeps the world alive. You control your characters, roll all the dice, track all the numbers, and make all the choices.

| You (the player) | The AI (via operators) |
|---|---|
| Create characters and crew | Narrate the world and NPCs |
| Roll dice and report results | Set position and effect for rolls |
| Track stress, harm, XP, coin | Apply consequences and complications |
| Decide what your characters attempt | Decide what happens as a result |
| Update KB objects with mechanical state | Update fronts and world state via `advance` |
| Design the world with `design` modules | Generate content within design sessions |

The workflow maps to Lens operators:
- **`design`** — Session zero: build setting (`--module world`), characters (`--module pc`), and story hooks (`--module front`). Also locations, NPCs, encounters as needed.
- **`play`** — All narrative during play. The AI reads pinned encounter objects, fronts, and location objects to run scenes. You direct your characters; it authors what happens.
- **`advance`** — End the day. The world takes its turn: fronts tick, events unfold, and your characters get downtime.

## The Dice

LitD uses six-sided dice (d6). When you roll, gather a pool of dice and read the **single highest result**:

- **6** — **Full success.** You do it. If you rolled more than one 6, it's a **critical** — you gain an additional advantage.
- **4 or 5** — **Partial success.** You do it, but there's a consequence.
- **1–3** — **Bad outcome.** Things go wrong.

If you have zero dice to roll (or negative), roll two dice and take the **lowest**. You can't get a critical with zero dice.

Even one die gives you a 50% chance of at least partial success. The system is generous — characters are competent, and the drama comes from consequences, not failure rates.

## Character Creation

This section is your reference for building a PC. None of this goes into the AI's prompt — it lives on your character sheet and in your `pc.*` KB object.

### 1. Name, Look, and Background

Freeform. Give your character a name, a few words describing how they look, and a sentence about their background — what they did before the story begins.

### 2. Actions

There are **9 actions** grouped into **3 attributes**:

| Insight | Prowess | Resolve |
|---|---|---|
| **Hunt** — track, shoot, ambush | **Finesse** — dexterity, precision, subtle manipulation | **Command** — compel, lead, intimidate |
| **Study** — scrutinize, research, analyze | **Prowl** — sneak, hide, move quietly | **Consort** — socialize, connect, blend in |
| **Survey** — observe, anticipate, read situations | **Skirmish** — fight in close quarters, brawl | **Sway** — persuade, deceive, charm |

Each action has a **rating** from 0 to 4 (the number of dots filled). At character creation, you have **7 action dots** to distribute, with a **maximum of 2** in any single action.

Your **attribute rating** (Insight, Prowess, or Resolve) equals the number of actions in that group that have **at least 1 dot**. So if you have dots in Hunt and Study but not Survey, your Insight rating is 2.

Attribute ratings matter for resistance rolls (how well you absorb consequences) and vice rolls (stress relief).

### 3. Special Abilities

Write **2–3 special abilities** that define what makes your character exceptional. Use these templates:

- **Bonus**: "+1d when [situation]." Grants an extra die in specific circumstances.
  *Example: "+1d when fighting from a hidden position."*

- **Armor**: "Mark special armor to resist [consequence type] or push yourself for [activity] without taking stress."
  *Example: "Mark special armor to resist fear or supernatural dread."*

- **Unlock**: "Push yourself (2 stress) to [extraordinary feat beyond normal limits]."
  *Example: "Push yourself to engage a small group on equal footing in melee."*

You have **one special armor box** that refreshes each time you rest. Abilities are recorded on your `pc.*` object.

### 4. Vice

Every character has a vice — an obsession they turn to for stress relief. Choose one and describe it briefly:

- **Faith** — devotion to a cause, power, or belief
- **Gambling** — games of chance, wagers, risk for its own sake
- **Luxury** — expensive pleasures, finery, comfort
- **Obligation** — service to family, community, or a cause
- **Pleasure** — lovers, food, drink, art, performance
- **Stupor** — oblivion through excess
- **Weird** — strange rituals, forbidden knowledge, alien experiences

Or invent your own. Name your vice purveyor — the person or place where you satisfy this need.

### 5. Stress, Trauma, and Harm

Start with:
- **9 stress boxes** (empty)
- **0 trauma conditions** (4 trauma = retire the character)
- **Empty harm track** (3 levels: lesser, moderate, severe; level 4 is fatal)

### 6. Write Your `pc.*` Object

Follow the `pc._template` in your dataset. At the bottom, add a `## Mechanics` section:

```
## Mechanics
- Actions: Hunt 1, Study 2, Finesse 1, Prowl 2, Skirmish 1
- Abilities: [list your special abilities]
- Vice: [type] — [brief description] (purveyor: [name])
- Stress: 0/9 | Trauma: 0/4
- Harm: [empty]
- XP: Insight 0/6, Prowess 0/6, Resolve 0/6, Playbook 0/8
```

## Crew Creation

The crew is the group your characters belong to. It's intentionally light — just enough to give the AI a sense of your group's scale and standing.

1. **Concept** — What is this group? A mercenary company, a band of explorers, a noble house's agents, a coven of witches? One or two sentences.
2. **Tier** — Start at **0**. This is your crew's power level, resources, and reach. It informs fortune rolls, the scale of opposition you face, and the quality of assets you can acquire.
3. **Rep** — A 12-segment clock. Fill it by completing operations (2 rep per operation, ±1 per tier difference with opposition). When full, pay coin equal to (new Tier × 8) to advance your Tier, then reset rep.
4. **Coin** — Start with **2**. Abstract wealth. Spend it on downtime, assets, and crew advancement. Earned through operations.

Record your crew in a `faction.*` or `lore.*` KB object.

## Playing the Game

### The Action Roll

When your character attempts something dangerous or uncertain, the AI will call for an **action roll**. Here's the sequence:

1. **You state your goal** and describe what your character does.
2. **You choose the action** that matches — if you're sneaking, that's Prowl; if you're fighting, Skirmish; if you're reading a situation, Survey.
3. **The AI sets position and effect:**
   - **Position** (how dangerous): controlled, risky, or desperate
   - **Effect** (how much you accomplish): limited, standard, or great
4. **You add bonus dice** (optional):
   - **+1d** from an ally's **assistance** (they take 1 stress)
   - **+1d** from **pushing yourself** (you take 2 stress) — also grants +1 effect instead of +1d if you prefer
   - **+1d** from a **devil's bargain** — the AI offers a consequence that happens regardless of your roll. You can reject it and push instead.
   - You can get at most one assist die and one push-or-bargain die.
5. **You roll** your dice pool and report the highest result. The AI narrates what happens.

**Position determines consequences:**

| | Critical | 6 | 4–5 | 1–3 |
|---|---|---|---|---|
| **Controlled** | Increased effect | You do it | Hesitate: withdraw, or do it with a minor consequence | Falter: seize a risky opportunity, or withdraw |
| **Risky** | Increased effect | You do it | You do it, but there's a consequence | Things go badly; you suffer a consequence |
| **Desperate** | Increased effect | You do it | You do it, but there's a severe consequence | It's the worst outcome |

The default is **risky / standard**. The AI won't always announce position and effect explicitly — sometimes it's obvious from the fiction. If you're unsure, ask.

### NPCs Don't Roll

Your action roll resolves both sides. On a 6, you win cleanly. On a 4–5, both you and the opposition have effect. On a 1–3, the opposition wins. The AI narrates what that looks like.

### Consequences

When you suffer a consequence, the AI will choose from:

- **Reduced effect** — Your action accomplishes less than expected
- **Complication** — A new problem arises (may tick a clock)
- **Lost opportunity** — That approach is closed; try something different
- **Worse position** — You're now in deeper trouble (controlled→risky→desperate)
- **Harm** — Physical or mental injury (see below)

A consequence should never negate a successful roll. If you rolled a 4–5, you succeeded — the consequence is the cost, not a reversal.

### Harm

Harm represents lasting injuries. There are three levels, each with a game effect:

| Level | Severity | Effect |
|---|---|---|
| 1 | **Lesser** (Battered, Drained, Distracted) | Reduced effect when it applies |
| 2 | **Moderate** (Deep Cut, Exhausted, Panicked) | -1d when it applies |
| 3 | **Severe** (Broken Leg, Shot, Terrified) | Need help to act |
| 4 | **Fatal** | Death |

You have two slots at each level. If a level is full, harm overflows to the next level up. Track harm on your character sheet with descriptive labels — not just numbers.

### Stress and Pushing

Stress is your currency for extraordinary effort and avoiding consequences:

- **Push yourself** (2 stress): +1d to a roll, OR +1 effect, OR act when incapacitated
- **Assist** an ally (1 stress): give them +1d
- **Resist** a consequence: make a resistance roll (see below)

When you fill your **9th stress box**, you suffer a **trauma condition** — a permanent personality shift (Cold, Haunted, Obsessed, Paranoid, Reckless, Soft, Unstable, or Vicious). Your stress resets to 0 and your vice is satisfied. When you mark your **4th trauma**, your character must retire.

### Resistance Rolls

When the AI inflicts a consequence you don't want to accept, say "I resist that." Roll your attribute:

- **Insight** — for consequences of deception, understanding, or awareness
- **Prowess** — for consequences of physical strain or injury
- **Resolve** — for consequences of mental strain, fear, or willpower

You always succeed — the consequence is reduced or avoided (the AI decides which). The cost is stress: **6 minus your highest die result**. On a critical, you **clear 1 stress** instead.

### Fortune Rolls

Sometimes the AI needs to decide something uncertain without a PC action — how loyal is that NPC? How bad is the storm? How much did the fire spread? The AI can ask you to make a **fortune roll**: roll a number of dice based on a relevant trait or situation, and the result guides what happens:

- **Critical**: Exceptional result
- **6**: Good result
- **4–5**: Mixed result
- **1–3**: Bad result

### Gathering Information

When you want to know something about the world, ask the AI. If it's common knowledge, you just get an answer. If there's uncertainty, the AI will call for an action or fortune roll, and the **effect level** determines how much detail you learn:

- **Great**: Exceptional detail, may reveal related secrets
- **Standard**: Good, clear information
- **Limited**: Partial or incomplete

### Devil's Bargains

Before you roll, the AI (or you!) can propose a devil's bargain: accept a complication or cost that happens **regardless of the roll result** in exchange for **+1d**. Common bargains:

- Collateral damage or unintended harm
- An item is lost or broken
- A faction is offended
- A clock ticks
- You suffer harm or attract attention

You can always reject a bargain and push yourself for the die instead. Bargains are optional.

## Flashbacks

One of the most powerful tools in LitD. When you're in a tight spot during play, you can declare: "I prepared for this." You flash back to an earlier moment and establish what you did.

**Cost in stress:**
- **0 stress**: Something you'd naturally have done (talked to a contact, packed a useful item)
- **1 stress**: Clever or unlikely preparation (bribed someone ahead of time, stashed a weapon)
- **2 stress**: Elaborate contingency (arranged a distraction, planted false evidence)

The AI may call for a roll within the flashback — it's handled like any other action. Flashbacks cannot undo what's already been established in the fiction. They reveal things that were always true but hadn't been mentioned yet.

**In Lens terms**: A flashback can be implemented as a narrative section that un-pins the current timeline, plays out a self-contained past moment, and applies its results when the section closes. This is one of the driving use cases for Lens's timeline system.

## Progress Clocks

Complex obstacles, mounting dangers, and long-term projects are tracked with **progress clocks** — circles divided into segments (4, 6, or 8).

- **4 segments**: A complex obstacle
- **6 segments**: A complicated obstacle
- **8 segments**: A daunting obstacle

Clocks track progress, not method. Name them after the obstacle ("Alert Level", "The Ritual", "Trust of the Elder") not the approach ("Sneak Past Guards").

**In Lens**: Progress clocks live in `front.*` KB objects. Fronts already track phased situations with timeline anchors and can be advanced by the `advance` operator. When the AI mentions a clock during play, the player should record it on the relevant front. The AI can reference clocks when setting position and effect.

Types of clocks:
- **Danger clocks**: GM ticks them on complications; when full, the danger manifests
- **Racing clocks**: Two opposed clocks; whoever fills theirs first wins
- **Project clocks**: Long-term efforts ticked during downtime

## Downtime

Downtime happens when you call `lens advance` to end the day. While the `advance` operator handles the world (ticking fronts, checking for events, generating consequences), each PC may perform **one downtime activity**:

### Recover
Seek treatment for harm. Roll your **Prowess** attribute (for physical harm) or **Resolve** (for mental harm). Tick segments on your **healing clock** (a 4-segment clock):

- **1–3**: 1 tick
- **4–5**: 2 ticks
- **6**: 3 ticks
- **Critical**: 5 ticks

When the healing clock fills, reduce every harm on your sheet by one level and clear the clock. Overflow ticks carry over.

### Project
Work on a **long-term project**. Describe what you do and roll a relevant action. Tick the project clock:

- **1–3**: 1 tick
- **4–5**: 2 ticks
- **6**: 3 ticks
- **Critical**: 5 ticks

Projects can be anything: researching a ritual, building an alliance, crafting an item, investigating a mystery.

### Indulge Vice
Satisfy your vice to clear stress. Roll your **lowest attribute rating**. Clear stress equal to your **highest die result**. If you clear more stress than you had marked, you **overindulge** — something goes wrong:

- **Attract Trouble**: A complication or unwelcome attention
- **Lost**: Your character vanishes for a while; play someone else until they return
- **Tapped**: Your vice purveyor cuts you off; find a new source

### Train
Mark **1 XP** on any attribute or playbook track. Simple and free.

### Extra Activities
Spend **1 coin** per additional activity beyond the first.

## Advancement

### XP Triggers

During play:
- Mark **1 XP** in the relevant attribute track when you make a **desperate action roll**

At the end of a session, review these triggers and mark 1 XP (or 2 if it happened a lot):
- You expressed your character's **beliefs, drives, or background**
- You **struggled** with your vice or trauma
- You addressed a challenge in a way that fits your **character concept**

End-of-session XP can go on any track.

### Advances

- **Attribute track** (6 segments): Add **+1 action dot** to any action in that attribute group (max 3, or 4 if the crew unlocks mastery)
- **Playbook track** (8 segments): Gain a **new special ability** (using the three templates)

### Crew Advancement

The crew earns **2 rep** per completed operation (±1 per tier difference with opposition). When the 12-segment rep clock fills:

- Pay **coin equal to new Tier × 8** to advance Tier. Reset rep.
- Or, if you can't pay, just reset rep and strengthen your crew's standing without advancing.

Higher Tier means better assets, stronger cohorts, and more formidable opposition taking you seriously.

---

## The Rules (AI Reference)

Below is the `rules.system` KB object — the concise mechanical reference pinned to the AI during play. It works alongside `rules.engagement` (which covers the authority model, decision gates, and scene guidance).

```kb
---
id: rules.system
---
LENS IN THE DARK — SYSTEM RULES
Based on Blades in the Dark by John Harper (CC BY 3.0). A Forged in the Dark game.

DICE

d6 pool. Read the single highest die:
- 6 = full success. Multiple 6s = critical (increased effect or additional benefit).
- 4–5 = partial success with consequence.
- 1–3 = bad outcome.
- Zero dice: roll 2d, take lowest. No critical possible.

ACTIONS AND ATTRIBUTES

9 actions in 3 attributes. Attribute rating = number of actions in that group with ≥1 dot.

- INSIGHT (Hunt, Study, Survey): perception, knowledge, anticipation.
- PROWESS (Finesse, Prowl, Skirmish): agility, stealth, combat.
- RESOLVE (Command, Consort, Sway): willpower, social influence, leadership.

Action ratings range 0–4. Attribute ratings range 0–3.

ACTION ROLLS

When a PC attempts something dangerous: player states goal and chooses action. You set position and effect.

Position (default risky):
- CONTROLLED — Low risk. 6: success. 4–5: minor consequence or withdraw. 1–3: falter; PC can seize risky opportunity or withdraw.
- RISKY — Uncertain. 6: success. 4–5: success + consequence. 1–3: bad outcome + consequence.
- DESPERATE — Danger. 6: success. 4–5: success + severe consequence. 1–3: worst outcome.
- Critical at any position: increased effect.

Effect (default standard):
- GREAT: full progress, 3 clock ticks. LIMITED: partial, 1 tick. STANDARD: expected, 2 ticks.
- Factors: potency, quality/tier, scale. Player may trade position↔effect.

Bonus dice (max +2d total):
- Assistance: +1d, ally takes 1 stress.
- Push: +1d (or +1 effect), PC takes 2 stress.
- Devil's bargain: +1d, a consequence occurs regardless of roll. Replaces push, not both.

NPCs never roll. The action roll resolves both sides.

CONSEQUENCES

Choose one or more: reduced effect, complication (tick a clock), lost opportunity, worse position, harm. Never negate a successful roll. Severity scales with position.

HARM

3 levels. Two slots each. Overflow moves up.
- Level 1 Lesser (Battered, Drained): reduced effect when applicable.
- Level 2 Moderate (Deep Cut, Exhausted): -1d when applicable.
- Level 3 Severe (Broken Leg, Terrified): incapacitated without help.
- Level 4 Fatal: death.

Healing: 4-segment clock filled via downtime Recover rolls. Full clock → all harm reduced by one level.

STRESS AND TRAUMA

9 stress boxes. Uses:
- Push yourself: 2 stress → +1d or +1 effect or act while incapacitated.
- Assist: 1 stress → give ally +1d.
- Resist: make a resistance roll (see below).

When stress fills: PC suffers a trauma condition (permanent personality shift: Cold, Haunted, Obsessed, Paranoid, Reckless, Soft, Unstable, Vicious). Stress resets to 0. Fourth trauma: retire character.

RESISTANCE ROLLS

Player declares resistance to a consequence. Roll attribute dice:
- Insight: vs. deception, understanding, awareness consequences.
- Prowess: vs. physical strain or injury.
- Resolve: vs. mental strain, fear, willpower.

Always succeeds (reduce or avoid consequence — you decide severity). Cost: 6 minus highest die = stress. Critical: clear 1 stress instead.

FORTUNE ROLLS

Your tool for disclaiming decisions. Roll a trait or situational dice pool:
- Critical: exceptional. 6: good/full. 4–5: mixed/partial. 1–3: bad/minimal.

Use for: NPC loyalty, off-screen events, weather, information quality, uncertain outcomes.

GATHERING INFORMATION

PC asks a question; roll action or fortune. Answer honestly; detail scales with effect:
- Great: exceptional detail, may reveal related information.
- Standard: good, clear answer.
- Limited: partial or incomplete.

SPECIAL ABILITIES

PCs define freeform abilities using three templates. Recognize and enforce these:
- BONUS: +1d in a stated situation.
- ARMOR: mark special armor box to negate/reduce a specific consequence type, or push for a specific activity without stress.
- UNLOCK: push yourself (2 stress) to perform an extraordinary feat.

Special armor refreshes on rest. PCs typically have 2–4 abilities.

FLASHBACKS

Player spends stress to establish a past preparation retroactively:
- 0 stress: ordinary, natural preparation.
- 1 stress: clever or unlikely.
- 2 stress: elaborate contingency.

May require an action roll. Cannot undo established fiction.

PROGRESS CLOCKS

Track complex obstacles, mounting dangers, and projects. In Lens, clocks live in front objects.
- 4 segments: complex. 6: complicated. 8: daunting.
- Name after the obstacle, not the method.
- Types: danger (ticked on complications), racing (two opposed clocks), project (ticked in downtime).

CREW

- Tier (0–4): crew's power level. Informs fortune rolls, NPC scale, asset quality.
- Rep: 12-segment clock. 2 rep per operation (±1 per tier difference). Full → advance tier (costs coin = new tier × 8).

DOWNTIME

Folded into the advance operator. Each PC gets 1 activity per day-end:
- Recover: roll attribute, tick healing clock (1–3→1, 4–5→2, 6→3, crit→5).
- Project: roll action, tick project clock.
- Indulge Vice: roll lowest attribute, clear stress = highest die. Overindulge if clearing more than marked.
- Train: mark 1 XP on any track.
Extra activity costs 1 coin.
```
