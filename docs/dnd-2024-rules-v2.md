# D&D 2024 Rules Reference for AI DM

> Mechanical foundation for AI operator prompts and KB entries.
> Sources: *Player's Handbook* 2024, *Dungeon Master's Guide* 2024, Sage Advice Compendium 2024.
> Voice: instructions to a model. No character creation, spell lists, feat catalogs, item catalogs, or adventure/campaign design.

---

## Part 1: The D20 System

### When to Call a D20 Test

Ask yourself four questions before calling any roll:

1. **Is a test warranted?** If the task is trivially easy or flatly impossible, don't roll.
2. **What kind?** Active attempt → ability check (or attack roll). Reactive avoidance → saving throw. Never conflate the three types.
3. **What ability/skill?** Choose what the character is using, not what would give the best odds.
4. **What's the DC?** Set it before the roll is made, never after.

Call for a roll only when **both success and failure are meaningful and possible**. Reward clever approaches that make failure implausible — let them work without rolling. Players tell you what their character attempts; you decide if a roll applies.

### The Three D20 Test Types

These are **distinct** — a rule affecting one does not affect the others unless it explicitly says "D20 Tests."

- **Ability Check**: Active task vs. challenge. Target: DC set by DM. Natural 1/20 is not auto-fail or auto-success.
- **Saving Throw**: Reactive resistance to an effect. Target: DC set by effect. Natural 1/20 is not auto-fail or auto-success.
- **Attack Roll**: Striking a target. Target: AC. Natural 1: auto-miss. Natural 20: Critical Hit (attack rolls only).

A natural 1 on an ability check or save is *not* automatic failure — it simply adds 1 to the result.

### Anatomy of a Roll

Roll 1d20 + ability modifier + Proficiency Bonus (if applicable) vs. DC or AC.

### Advantage and Disadvantage

**Advantage**: roll two d20s, use the higher. **Disadvantage**: roll two d20s, use the lower.

- Multiple sources of Advantage or Disadvantage **do not stack** — still only two dice.
- One source of each **exactly cancels** regardless of count — roll one d20.
- Advantage/Disadvantage applies *after* any reroll — the reroll replaces one die, not both.

**Heroic Inspiration (2024):** Spend to reroll any single die immediately after rolling; must use the new result. Can't stockpile — give excess to another PC.

### Difficulty Classes

- DC 5 (Very Easy): Skip unless circumstances are unusual.
- DC 10 (Easy): A character with ability 10, no proficiency succeeds ~50%.
- DC 15 (Medium): Needs higher score or proficiency for a ~50% chance.
- DC 20 (Hard): Typically needs both.
- DC 25 (Very Hard): Exceptional characters only.
- DC 30 (Nearly Impossible): Reserved for legendary feats.

When you can't decide between adjacent DCs, pick the harder one — meaningful risk drives better fiction.

**Calculated DCs:** When a task directly opposes another creature's action, DC = 8 + that creature's relevant ability modifier + Proficiency Bonus. Use for Stealth vs. Perception, Deception vs. Insight, etc.

### Group Checks

When the whole group attempts the same task (sneaking past guards, navigating fog), have everyone roll. If more than half succeed, the group succeeds.

### Passive Checks

Use a creature's passive score (10 + modifier + Proficiency Bonus if proficient) when you don't want to tip off players by asking for a roll, or when checking for background awareness. Passive Perception (10 + Wis modifier, + Prof if proficient) is the DC for noticing a hidden creature or object without actively searching.

### Skills Reference

- Acrobatics (Dex): Balance, tumbling, tricky movement
- Animal Handling (Wis): Control, calm, or read animals
- Arcana (Int): Magic lore, spell identification, planar knowledge
- Athletics (Str): Climbing, jumping, swimming, grappling, shoving
- Deception (Cha): Lying, misdirection, disguise
- History (Int): Lore, events, lineages, geography
- Insight (Wis): Detecting lies, reading motive, sensing attitude
- Intimidation (Cha): Threats, coercion, hostile pressure
- Investigation (Int): Clues, deduction, searching for hidden mechanisms
- Medicine (Wis): Stabilizing the dying, diagnosing poison/disease
- Nature (Int): Terrain, plants, animals, weather, natural cycles
- Perception (Wis): Noticing things; drives Passive Perception
- Performance (Cha): Entertaining an audience
- Persuasion (Cha): Convincing through good faith, tact, or appeal
- Religion (Int): Divine lore, rituals, undead, celestials, fiends
- Sleight of Hand (Dex): Pickpocketing, palming objects, legerdemain
- Stealth (Dex): Moving quietly, hiding from notice
- Survival (Wis): Tracking, foraging, navigation, weather reading

**Proficiency:** Add Proficiency Bonus to applicable D20 Tests; never stacks or duplicates. Expertise doubles Proficiency Bonus for one specific skill.

### Consequences — Beyond Pass/Fail

Don't treat every result as binary. Options:

- **Success at a cost:** The character achieves the goal but suffers a complication — injury, alarm raised, resource spent, worse position.
- **Degrees of failure:** Failure by 5+ triggers a worse outcome than a narrow miss. A narrow miss might mean "not yet" while a large failure triggers a trap or escalation.
- **Degrees of success:** Exceeding the DC by 5+ can yield extra information, faster completion, or a bonus effect.
- **"Yes, and":** When players propose unexpected approaches, accept and add a consequence or twist.
- **"No, but":** When something can't work, block that path while offering a different lead or partial progress. Never a pure dead end.

### Improvising Damage

When an effect causes harm outside normal rules:

- Nuisance (minor hazard, brief exposure): 1d10 (levels 1–4), 2d10 (5–10), 4d10 (11–16), 10d10 (17–20)
- Deadly (significant threat, could kill): 2d10 (1–4), 4d10 (5–10), 10d10 (11–16), 18d10 (17–20)

---

## Part 2: Actions, Bonus Actions, Reactions

### The Action Economy

Each turn: **move** (up to Speed) + **one Action** + **one Bonus Action** (if available). Each round: **one Reaction** (resets at start of your turn). Only one thing at a time — no creature takes two Actions on the same turn except by features that explicitly grant extras.

### Standard Actions

- **Attack**: Make one attack (or more if Extra Attack applies).
- **Dash**: Gain extra movement equal to Speed this turn.
- **Disengage**: Movement doesn't provoke Opportunity Attacks for the rest of the turn.
- **Dodge**: Until start of your next turn — attacks against you have Disadvantage; you have Advantage on Dex saves. Lost if Incapacitated or Speed = 0.
- **Help**: Give an ally Advantage on their next ability check or attack roll (must be adjacent for attack help). Or use Medicine DC 10 to stabilize a dying creature.
- **Hide**: Dex (Stealth) check vs. DC 15 while Heavily Obscured or behind Three-Quarters/Total Cover, out of every enemy's line of sight. Success → **Invisible condition**. Ends when: you make noise louder than a whisper, an enemy finds you, you make an attack roll, or you cast a spell with a Verbal component.
- **Influence**: Cha (Deception/Intimidation/Performance/Persuasion) or Wis (Animal Handling) check to alter an NPC's attitude.
- **Magic**: Cast a spell, activate a magic item, or use another magical ability. **Cantrips** require no spell slot and scale by character level. **Ritual** spells take 10 minutes longer but consume no spell slot. **Concentration**: only one Concentration spell active at a time; taking damage requires a Con save (DC = max of 10 or half damage taken) to maintain; Incapacitated breaks Concentration automatically.
- **Ready**: Declare a perceivable trigger and a response. When the trigger occurs, use your Reaction to execute. Readied spells are cast now, slot expended, released on trigger — if not released before your next turn, the slot is lost. You can abandon a readied Reaction to take an Opportunity Attack instead, but you have only one Reaction.
- **Search**: Wis (Perception) or Int (Investigation) check to find something.
- **Study**: Ability check to glean information (Arcana for a magic item, History for a creature's legend, Medicine for a condition's cause).

### Bonus Actions and Reactions

**Bonus Actions** are available *only* when a feature, spell, or rule explicitly grants one — they cannot substitute for an Action, nor vice versa.

**Reactions** trigger on specific events. One Reaction per round.

**Opportunity Attack (Reaction):** When a creature you can see **voluntarily leaves your reach** using its action, Bonus Action, Reaction, or Speed — make one melee attack against it. Does *not* trigger on teleportation, involuntary movement, or Disengage. If a readied Reaction and an OA opportunity arise simultaneously, choosing the OA consumes your Reaction and the readied action is lost.

---

## Part 3: Social Interaction

### NPC Attitudes

- **Friendly**: Views you favorably. Advantage on Charisma checks to influence them.
- **Indifferent**: Neither hostile nor helpful. No modifier.
- **Hostile**: Opposes you. Disadvantage on Charisma checks to influence them.

Attitude governs starting posture, not absolute compliance. A Friendly NPC can still refuse a dangerous request; a Hostile NPC can still be bargained with under extreme pressure.

### Running Social Encounters

Balance free roleplaying with ability checks — don't call for checks on every exchange, and don't skip them when stakes are real. If a player delivers a compelling in-character argument, reward it without demanding a Persuasion roll. Call checks when the NPC's resistance is meaningful and both outcomes (compliance and refusal) are interesting.

### Influence Action

Cha (Deception, Intimidation, Performance, or Persuasion) or Wis (Animal Handling) check. On success, attitude shifts one step toward Friendly or NPC complies with a reasonable request. On failure, don't slam the door — offer partial results, complications, or a changed approach that might work.

---

## Part 4: Exploration

### Vision and Light

- **Bright Light**: Normal vision.
- **Dim Light**: Lightly Obscured — Disadvantage on sight-based Perception checks.
- **Darkness**: Heavily Obscured — effectively Blinded for sight.

**Darkvision:** Treats darkness as dim light within its range. Cannot see color. Does not grant normal vision in dim light.

**Magical Darkness:** Only blocks Darkvision if the specific effect's text says so — the *Darkness* spell explicitly does; generic magical darkness does not.

**Blindsight:** Perceives within range regardless of light or Invisible condition. Finding a hidden creature removes their Hidden status entirely.

**Truesight:** Sees through darkness, Invisible condition, illusions, and into the Ethereal Plane within range.

### Hiding

The **Hide action** requires a Dex (Stealth) check vs. DC 15 while Heavily Obscured or behind Three-Quarters/Total Cover, out of every enemy's line of sight. Record the check result — it becomes the DC for an enemy's Perception check to find the hidden creature. Success grants the **Invisible condition** while hidden.

Use Passive Perception when you don't want to telegraph hidden things. Use active Perception checks when characters are actively searching.

### Perception and Encounter Distance

- Quiet conditions — Audible: 2d6 × 10 ft; Visual: clear line of sight
- Noisy conditions — Audible: 2d6 × 50 ft; Visual: limited if lightly obscured
- Heavily obscured (fog, dark) — Visual: 10–30 ft

### Travel

- Fast (4 mi/hr, 30 mi/day): −5 to Passive Perception
- Normal (3 mi/hr, 24 mi/day): no effect
- Slow (2 mi/hr, 18 mi/day): can use Stealth

Break longer trips into 2–3 stages, each with one challenge type (encounter, foraging, navigation, hazard, or search opportunity). Unimportant travel can be glossed over in a sentence.

### Hazards

- **Falling**: 1d6 Bludgeoning per 10 feet, max 20d6. Lands Prone unless takes 0 damage. DC 15 Str (Athletics) or Dex (Acrobatics) to halve damage falling into liquid.
- **Suffocation**: Hold breath for 1 + Con modifier minutes (min 30 sec). After that, drop to 0 HP at the start of each turn.
- **Dehydration**: 1 day without water → 1 Exhaustion level per hour thereafter until drinking.
- **Malnutrition**: 3 + Con modifier days without food → 1 Exhaustion level per day.
- **Extreme Cold** (0°F or below): DC 10 Con save per hour or 1 Exhaustion level. Immune: cold resistance/immunity, appropriate gear.
- **Extreme Heat**: DC 5 Con save per hour (DC +1 per hour) or 1 Exhaustion level. Immune: fire resistance/immunity, appropriate gear.
- **High Altitude** (above 10,000 ft, unacclimatized): Exhaustion after 1 hour; Disadvantage on Str/Con checks and saves.
- **Deep Water** (below 100 ft, no Swim Speed): DC 10 Con save per hour or 1 Exhaustion level.

### Environmental Effects

- **Slippery Ice**: Difficult Terrain. Walking requires DC 10 Acrobatics or fall Prone.
- **Strong Wind**: Disadvantage on ranged attack rolls. Concentration checks for spells with Verbal components may be warranted.
- **Thin Ice**: Crack threshold 3d10 × 10 lbs. Heavier creatures break through into icy water.
- **Dead Magic Zone**: As Antimagic Field spell — all magic ceases within (typically ≤300 ft diameter).
- **Wild Magic Zone**: Spellcasting triggers a Wild Magic surge.

---

## Part 5: Combat

### Starting Combat

Combat starts when — and only when — you say it does. Don't let players roll Initiative by fiat; some class features trigger on Initiative rolls. If a character initiates hostilities (casting a spell, making an attack), give them Advantage on their Initiative roll.

### Initiative

Roll 1d20 + Dexterity modifier. Higher result acts first. **You cannot delay your turn** — if a player wants to act later in response to something, they take the Ready action. Ties: DM decides (or use Dex score as tiebreaker, or act simultaneously).

**Surprise (2024):** A creature that doesn't notice combat beginning has **Disadvantage on its Initiative roll**. Surprise is not a skipped turn — just a disadvantaged roll.

### On Each Turn

In any order: **move** (up to Speed, can split before/after actions) + **one Action** + **one Bonus Action** (if available). Free actions: talking, gesturing, dropping an item.

### Movement

- **Difficult Terrain**: 2 feet of movement per foot traversed. Does not stack — always costs 2 ft/ft.
- **Dropping Prone**: Free. Standing up costs half your Speed.
- **Passing through spaces**: You can move through an ally's, Incapacitated creature's, Tiny creature's, or a creature 2+ sizes different from yours. You cannot willingly **end** your move in another creature's space.
- **Diagonal movement (grid)**: Count every other diagonal as 2 squares (1–2–1–2 rule), or each as 1 for simplicity — decide consistently.

### Creature Sizes

- Tiny: 2.5 × 2.5 ft (¼ square)
- Small / Medium: 5 × 5 ft (1 square)
- Large: 10 × 10 ft (2 × 2 squares)
- Huge: 15 × 15 ft (3 × 3 squares)
- Gargantuan: 20 × 20 ft or larger (4 × 4 squares+)

### Making an Attack

1. Choose target within range.
2. Apply Advantage/Disadvantage (conditions, cover, range, melee with ranged weapon).
3. Roll attack; compare to target's **Armor Class (AC)** — must meet or beat it to hit.
4. On hit, roll damage.

**Ranged attacks**: Normal range / long range listed as "X/Y ft." Attacking beyond normal range up to long range: Disadvantage. Beyond long range: impossible. Attacking while a **hostile creature is adjacent**: Disadvantage on ranged attacks.

**Melee attacks**: Default reach 5 feet; some weapons/features extend to 10 feet.

**Line of Sight**: Trace an imaginary line from any corner of your space to any part of the target's space. If the line passes through or touches a vision-blocking object, you lack line of sight and cannot target directly.

### Opportunity Attacks

Triggered when a creature you can see **voluntarily leaves your reach** (using action, Bonus Action, Reaction, or Speed). Use your Reaction to make one melee attack. Does *not* trigger on teleportation, involuntary movement, or Disengage. Taking an OA consumes your Reaction and any readied action is lost.

### Cover

- **Half Cover**: +2 to AC and Dex saves
- **Three-Quarters Cover**: +5 to AC and Dex saves
- **Total Cover**: Can't be directly targeted

An intervening creature grants the target **Half Cover (+2 AC)** — it does *not* impose Disadvantage on the attacker's roll.

### Mounted Combat

**Controlled mount** (trained): Initiative changes to match rider's; can only Dash, Disengage, or Dodge; moves on rider's turn. **Independent mount**: keeps own Initiative, acts freely. If mount is moved involuntarily or knocked Prone, rider makes DC 10 Dex save or falls off (Prone, up to 5 feet away).

### Underwater Combat

Melee weapons without the Thrown property have Disadvantage unless the attacker has a Swim Speed. Ranged weapon attacks (not crossbows) have Disadvantage and auto-miss at long range. No Swim Speed → water is Difficult Terrain.

### Running Combat Well

- Monsters pursue **goals**, not nearest enemies — the cornered captain grabs a hostage; losing minions break and run; intelligent undead retreat to a chokepoint. Sapient monsters may parley mid-combat if the tide turns.
- **Share information** as it becomes apparent — if a Fire Bolt hits a Fire Elemental and does nothing, tell the players the spell didn't seem to bother it.
- **Hasten certain outcomes** — if victory is clearly inevitable and combat is dragging, simply have the last monster drop.
- **Adjust difficulty via fiction**, not dice: have monsters flee when bloodied, call in reinforcements, change terrain, or switch tactics entirely.

### Mobs

When running large groups of identical monsters:

- Use **average damage** from the stat block instead of rolling.
- If a spell/attack reduces a monster to a handful of HP, assume it's eliminated.
- **Divide into mobs of 5–8** identical creatures; spread their turns between character turns. Never more mobs than characters.
- **Average results without rolling**: Find the minimum roll needed to succeed, find the percentage of d20 rolls at or above that number, apply that fraction to the mob count. (E.g., 10 orcs need 15+; ~30% of rolls are 15+; ~3 succeed.)

### Chases

Use chase rules instead of normal movement (which makes chases mechanical and predictable):

- Roll Initiative when the chase begins. Track distance between quarry and pursuers instead of exact positions.
- **Dashing**: After two consecutive Dashes, a creature must make a DC 10 Constitution check or gain 1 Exhaustion level.
- Each round, roll on a Chase Complications table (urban or wilderness) to introduce obstacles.
- The quarry **escapes** when: distance exceeds pursuit range; out of sight for 3 consecutive rounds (requires 3 consecutive DC 15 Perception or Survival checks to reacquire); or they enter a space the pursuer can't follow.
- The pursuer **catches up** when distance closes to melee reach.

---

## Part 6: Damage and Healing

### Hit Points

HP represents durability and will to live. Loss has **no mechanical effect on capabilities** until HP reaches 0. **Bloodied (2024)**: at or below half HP maximum — narrate it visibly; some monster abilities trigger on this state.

### Damage Rolls

Roll the damage dice specified. For weapons, add the relevant ability modifier. Most spell damage rolls *don't* add an ability modifier unless the spell text says so.

**Critical Hit** (natural 20 attack roll): Roll **all** damage dice twice — don't just double the total. Add modifiers once. Applies to weapon damage and any additional dice (e.g., Sneak Attack dice are also doubled).

**Saving throw damage**: Full damage on a failed save. Half damage (round down) on success, unless the effect says "no damage on a successful save."

**Damage types**: Acid, Bludgeoning, Cold, Fire, Force, Lightning, Necrotic, Piercing, Poison, Psychic, Radiant, Slashing, Thunder. Types matter only in context of Resistance, Immunity, or Vulnerability.

### Resistance, Immunity, Vulnerability

- **Resistance**: Halve damage of that type (round down). Applied once per instance regardless of how many sources apply.
- **Immunity**: Take no damage of that type, or in the case of a condition, are unaffected by it.
- **Vulnerability**: Double damage of that type.
- **Order when multiple apply**: Vulnerability first (×2), then Resistance (÷2) — net result is normal damage. They don't cancel each other.

**Simultaneous effects**: When two effects happen at the same moment, the affected creature (or their controller) chooses the order of application.

### Healing

Restores current HP up to (not exceeding) maximum. Cannot heal a dead creature.

### Dropping to 0 HP

**Instant Death**: If damage from a single hit reduces HP to 0 and the leftover damage equals or exceeds HP maximum, the creature dies instantly.

**Falling Unconscious**: Otherwise, creature gains the Unconscious condition and begins **Death Saving Throws** at the start of each of its turns:

- 10+ = success; 9 or lower = failure
- 3 successes → stable; 3 failures → dead
- Natural 20 → immediately regain 1 HP (conscious, Prone)
- Natural 1 → counts as 2 failures
- Taking any damage while at 0 HP → 1 death save failure; a Critical Hit → 2 failures
- Any healing (any amount) → HP restored, process ends

**Stabilizing**: Help action + DC 10 Wis (Medicine) → creature is stable. No longer makes death saves. Regains 1 HP after 1d4 hours.

**Knocking Out**: When a melee attack would reduce a target to 0 HP, the attacker may choose to knock out instead → drops to 0 HP, Unconscious, begins a Short Rest.

### Temporary Hit Points

Separate pool. Damage depletes Temp HP first, then HP. **Do not stack** — take the higher of existing vs. new grant. Healing does not restore Temp HP. Not real HP — spells/features that trigger on healing do not trigger from Temp HP.

---

## Part 7: Conditions

Conditions are binary (you have it or you don't) except Exhaustion. Multiple applications of the same condition share the longest duration — effects don't compound. To remove a condition: meet its counter (stand up for Prone, end Concentration for Incapacitated via that route) or let the effect expire.

**Blinded**: Can't see; auto-fail sight-based checks. Attacks against you: Advantage. Your attacks: Disadvantage.

**Charmed**: Can't attack the charmer or target them with harmful effects. Charmer has Advantage on social ability checks with you.

**Deafened**: Can't hear; auto-fail hearing-based checks.

**Exhaustion**: Cumulative levels 1–5; death if level would exceed 5. Each Long Rest reduces by 1.

- Level 1: Disadvantage on all d20 Tests
- Level 2: Speed halved
- Level 3: Disadvantage on attack rolls and saving throws
- Level 4: HP maximum halved
- Level 5: Speed = 0

**Frightened**: Disadvantage on ability checks and attack rolls while source of fear is within line of sight. Can't willingly move closer to the source. Note: Disadvantage applies even if the source is imperceptible, as long as you have line of sight to its space.

**Grappled**: Speed = 0 (can't increase). Disadvantage on attacks against targets other than the grappler. Grappler can drag/carry you — costs 1 extra ft per ft moved unless you're Tiny or 2+ sizes smaller. A grappler who falls Prone does *not* make the grappled creature Prone.

**Incapacitated**: Can't take Actions, Bonus Actions, or Reactions. Breaks Concentration. Can't speak.

**Invisible**: Not affected by effects requiring sight unless the perceiver can see the creature. Attacks against you: Disadvantage. Your attacks: Advantage. If Invisible when rolling Initiative: Advantage on the roll.

**Paralyzed**: Has Incapacitated. Speed = 0. Auto-fail Str and Dex saves. Attacks against you: Advantage. **All hits within 5 feet are Critical Hits.**

**Petrified**: Transformed into inanimate solid. Has Incapacitated. Speed = 0. Auto-fail Str and Dex saves. Attacks against you: Advantage. Resistance to all damage. Immune to Poisoned condition.

**Poisoned**: Disadvantage on attack rolls and ability checks.

**Prone**: Movement by crawling only (costs double Speed). Attacks against you from within 5 feet: Advantage; from beyond 5 feet: Disadvantage. Your melee attacks: Disadvantage. Counter: stand up by spending half Speed.

**Restrained**: Speed = 0. Your attacks: Disadvantage. Attacks against you: Advantage. Disadvantage on Dex saves.

**Stunned**: Has Incapacitated. Speed = 0. Auto-fail Str and Dex saves. Attacks against you: Advantage. Note: Stunned no longer prevents movement in 2024 rules — Speed 0 still pins the creature in practice, but Paralyzed is the harder version (all close hits are Crits).

**Unconscious**: Has Incapacitated. Speed = 0. Falls Prone. Auto-fail Str and Dex saves. Attacks against you: Advantage. **All hits within 5 feet are Critical Hits.** Unaware of surroundings.

### Fear and Mental Stress

Use the **Frightened condition** as the baseline for supernatural fear. Wisdom saving throw; calibrate DC by situation:

- DC 10: Harmless apparition in a sarcophagus
- DC 15: Magical trap creates illusory manifestation of greatest fear
- DC 20: Party faces a CR 13+ undead for the first time
- DC 25: Witnessing a god's true form

**Mental Stress**: For psychically or cosmically overwhelming encounters, consider a short-term mental stress effect (lasting minutes to hours) in addition to or instead of Frightened. Discuss with players before using these mechanics — they can be uncomfortable.

---

## Part 8: Resting

**Short Rest**: At least 1 hour of light activity. Spend any number of Hit Dice (roll each + Con modifier) to regain HP. Must have at least 1 HP to begin. DM controls pacing by controlling when safe downtime is available.

**Long Rest**: At least 8 hours (6 hours sleep, no more than 2 hours light activity). Must have at least 1 HP to begin. Cannot start another Long Rest until 16 hours have passed. On completion: all lost HP restored; all spent Hit Dice restored; Exhaustion reduced by 1; most class features recharge. Features that recharge "per day" recharge on a Long Rest, not at midnight.

---

## Part 9: NPCs

NPCs have an attitude (Friendly/Indifferent/Hostile), one or two personality adjectives, and a secret goal. Their full details are managed as KB objects.
