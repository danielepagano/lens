# [DESIGN MODULE]: CUSTOM STAT BLOCK

Build a `stat.*` block for a creature the reference material does not have — a boss, a named NPC's sheet, a themed variant, a creature built around a mechanic you want in play. Reach for it when a scene needs a creature nobody wrote, including mid-session when the encounter you are building turns out to need one.

`stat._template` has the shape and the tag vocabulary. What follows is the order of the work, which is where custom creatures actually go wrong: everything before the writing.

`rules.stat` is here too, and it is not for copying: it is how `play` will *use* what you write — act only from the block, Multiattack is the whole Action, the player resolves every roll. The block you emit is a rider to it. Never restate a line of it inside the block.

1: THE TARGET CR

A creature's CR is its own property and you can settle it independently. What the situation sets is the **mix** — how many of them, alongside what, against whom. Take whichever of the two you were given; if there is no situation yet, a CR and a role (solo, one of several, the leader of lesser creatures) is a complete brief on its own.

`balance_encounter` prices a roster against a party's XP budget, and **every slot is either a stat id or a bare challenge rating** — so the creature you are about to write is priced as its rating, before it exists. That makes the tool a way to ask questions rather than a final check: `required: [{"id": "3", "count": 1}]` with `optional: ["stat.zombie", "stat.skeleton"]` asks what a CR 3 enemy plus some undead comes to, and moving the rating up or down tells you what this creature can afford to be. Ratings work in `allies` too. Call it as often as the mix keeps changing; iterating is the point. When there is no party and no roster, skip it — the arithmetic below is what validates the block.

Where a situation *is* known, it decides what that CR gets spent on:

- lethal, or merely interesting — they are not the same brief
- does it have help? If minions carry the damage, the creature buys control and staying power instead
- does the ground help the party (cover, allies, something breakable, a lateral way to win) or hurt them (reinforcements, a deadline, having to stay quiet)?
- does the party have to kill it, or only survive it, escape it, or delay it?

Where that is still open, err toward a creature the situation can make harder later. An under-tuned creature in a lair that can escalate is recoverable mid-scene; an over-tuned one is not.

2: WHAT IT IS FOR

One sentence, narrative and mechanical, before any numbers. A block for an existing `npc.*` has to deliver how *that* character solves problems — a generic block with their name on it fails even with perfect math. A block built around a mechanic names the mechanic. An ally's block also has to be bearable to fight alongside, and it counts on the party's side of the budget.

How the creature behaves is **mechanism, and therefore yours**: what it opens with, what it does when it is hurt, what it will not do, what makes it stop. Decide those and write them down. The decision to hand back is a story fact nobody told you — who this creature really is, why it is here, what it serves — never how it acts.

So ask about the situation, which only the user has: the party, how many of these there are, what winning means here. Do not ask what its escalation looks like, how hard it hits, or what it does when the trigger fires — "what happens when it stops holding back?" is not a story question, it is the block you were asked for. And read what is already in front of you before asking anything: a pinned encounter usually states the stakes and the way the scene ends.

3: HARVEST FIRST

Nothing gets written until real blocks are in front of you, and that is two different searches:

- **At the CR** — `kb_with_tag ["stat", "(cr:4 cr:5 cr:6)"]`, then `kb_get` two or three. These are the real numbers at this CR, and they beat any table.
- **On theme** — `type:`, `habitat:`, or the closest published creature by concept. These are the pieces worth taking: the mechanic, the reaction, the phrasing that already works.

A published block with a new name and one ability swapped is often the better answer, and it has already been played.

4: COHESION

The taste pass, before the arithmetic. Consider:

- whether these abilities belong to one creature, and what is only there because the CR needed filling
- what one of its turns buys — Action, Bonus Action, Reaction, legendary actions — and whether it still has something to do when the party does the obvious thing to it
- how much of it is damage and how much is nuisance, and whether that matches what the creature is for
- **count first**: a creature that appears N at a time has every number on it multiplied by N — N turns, N attacks, N riders, N saves the party has to make. Run the two checks below at the count it will actually show up in, not at one.
- **the one-round check**: everything it can pour into a single PC in one round, against the most fragile PC's hit points, healthy and again at half. A boss that takes a healthy martial from full to dead inside one round is a bloodbath — limit how much can land on one target, or trade damage for control. This matters most below level 5.
- roughly how many rounds the party needs to drop it, and how many it needs to drop someone
- whether its worst ability can be seen coming. A tell in the block — a wind-up, a glow, what it did to the last person who stood there — is what licenses that ability to hit hard.
- how it stops: a wound threshold, an ally count, a spent resource. A creature that always fights to 0 hit points is a worse scene.
- legendary actions and Legendary Resistance are features of creatures met *above* the party's tier, not the way to make a mid-CR solo survive. Reach for hit points, a reaction, position, and terrain first — check what the published blocks at your CR actually have before giving it either.
- an ability that repeatedly takes away a PC's turn takes the player out of the game, however balanced it looks — and a rider on a creature used six times is six chances a round, which is not the same ability at all
- a state you name on the block has to keep working in scenes nobody has written yet, so it can only be a flavoured shortcut over rules that already exist: "Waterlogged: its Speed is halved until it leaves the water" — one effect, one obvious way out, no subsystem. Where an existing condition fits, name that instead; the table already knows it. Anything with more moving parts than a line does not belong on a block at all — it belongs in the encounter, which knows the room and can afford "when the keeper drags you under, this is what happens"

5: THE MATH

Medians of every published block in the D&D corpora (511 of them):

| CR | AC | HP | best attack | save DC |
|---|---|---|---|---|
| 1/4 | 12 | 13 | +4 | 11 |
| 1/2 | 12 | 19 | +4 | 11 |
| 1 | 13 | 26 | +4 | 11 |
| 2 | 13 | 45 | +5 | 12 |
| 3 | 14 | 65 | +5 | 12 |
| 4 | 15 | 71 | +5 | 13 |
| 5 | 15 | 94 | +7 | 15 |
| 6–8 | 15–16 | 110 → 136 | +7 | 15 |
| 9–12 | 17–18 | 156 → 178 | +9 | 17 |
| 13–16 | 18–19 | 192 → 252 | +10 → +12 | 18 |
| 17–20 | 19–20 | 234 → 323 | +13 | 20 |
| 21+ | 21+ | 333+ | +15 | 22 |

Where a row spans several CRs, the numbers span them in order: a creature at the bottom of the band takes the bottom number.

Between rows: HP ≈ 15 + 15×CR (≈ 315 + 50×(CR−20) above 20), AC ≈ 14 + CR/3, attack ≈ 4 + CR/2, save DC ≈ 11 + CR/2, damage per round ≈ 7.5×CR. These are population fits, not targets — the four are not tightly correlated in the published blocks either. Two adjustments worth making: a solo creature absorbing a whole party's output alone wants roughly half again the table's hit points, and a resistance only counts as extra effective hit points if this party brings that damage type.

Then make the block internally consistent, which is a different job from matching the table:

- Proficiency bonus from CR: **+2** (CR 0–4), **+3** (5–8), **+4** (9–12), **+5** (13–16), **+6** (17–20), **+7** (21–24), **+8** (25–28), **+9** (29–30).
- Attack bonus = ability mod + PB. Save DC = 8 + ability mod + PB. A skill = ability mod + PB (double PB where the creature is exceptional). Passive Perception = 10 + WIS mod, plus PB if proficient in Perception.
- Hit points are **computed**: pick a number of hit dice for the size (Tiny d4, Small d6, Medium d8, Large d10, Huge d12, Gargantuan d20), then HP = the dice average plus the CON modifier once per die, rounded down at the end — 15d8 with CON +2 is 67 + 30 = 97, the published Assassin. Choose the dice count that lands nearest the table's row for this CR. Damage expressions print dice and average, and the average matches the dice: one die averages **d4 2.5, d6 3.5, d8 4.5, d10 5.5, d12 6.5**, so Nd8+M is 4.5×N+M, **always rounded down** — 2d8+2 is 11 and never 13, and 1d10+3 is 8 and never 9.
- **Change an ability score and every number that derives from it moves.** Raising a scout's DEX by 2 moves its AC, its initiative, every finesse and ranged attack bonus, that attack's damage, Stealth, Acrobatics, and its DEX saves. Half-updated blocks are the most common defect in custom creatures, and they are invisible until play.

Before emitting, run **`check_stat`** on the block. It proofreads exactly this: every attack bonus against a mod + PB, every save DC against 8 + a mod + PB, every damage average against its dice, the tags against the vocabulary, and it shows what published blocks at this CR actually look like. It is arithmetic only and has no opinion on the creature, so a clean report is not approval — it means the numbers are consistent and the remaining question, the one this module is about, is whether the creature is worth playing against.

The block owns the creature and nothing else. Where the scene already carries a rule — the encounter's own scene rules, a hazard, a mechanism — the block says what this creature *does* with it and never restates or redefines it. An ability whose effect is "GM's call" is not an ability; give it a number or leave it out.

6: ITERATE

Read the result from the top against step 1, as if you had not written it: is this appropriate, interesting, and balanced for that situation? Then stop; another pass of taste beats another ability.

TAGS

Never invent a tag. Use the vocabulary in `stat._template` and nothing else — an invented tag matches nothing and no later search will find it. `cr:` is not optional: `balance_encounter` reads XP from it, and a block without one is silently worth 0.
