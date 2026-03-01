# D&D 2024 Rules Reference for AI DM

> Mechanical foundation for AI operator prompts and KB entries.
> Sources: *Player's Handbook* 2024, *Dungeon Master's Guide* 2024, Sage Advice Compendium 2024.
> Voice: instructions to a model. No character creation, spell lists, feat catalogs, item catalogs, or adventure/campaign design.

---

## Chapter Map


| Book | Chapter                                 | DM Relevance                                                                     |
| ---- | --------------------------------------- | -------------------------------------------------------------------------------- |
| PHB  | 1: Playing the Game                     | **Core — master this**                                                           |
| PHB  | 2: Creating a Character                 | Low — player's domain                                                            |
| PHB  | 3–6: Classes, Origins, Equipment, Feats | Low — know they exist; ask the player for details                                |
| PHB  | 7: Spells                               | Medium — know schools, ranges, targets, Concentration rules; players track slots |
| PHB  | Rules Glossary                          | **Core — canonical term definitions**                                            |
| DMG  | 1: The Basics                           | Low — table logistics, session zero framing                                      |
| DMG  | 2: Running the Game                     | **Core — adjudication wisdom**                                                   |
| DMG  | 3: DM's Toolbox                         | Medium — optional mechanics as needed                                            |
| DMG  | 4–5: Adventures, Campaigns              | Out of scope for this doc                                                        |
| DMG  | 7: Treasure                             | Out of scope (item catalog)                                                      |


---

## Part 1: The D20 System

### When to Call a D20 Test

Ask yourself four questions before calling any roll:

1. **Is a test warranted?** If the task is trivially easy or flatly impossible, don't roll. A character crosses an empty room without a Dexterity check; no lucky roll lets an ordinary bow hit the moon.
2. **What kind?** Active attempt → ability check (or attack roll). Reactive avoidance → saving throw. Never conflate the three types.
3. **What ability/skill?** Choose what the character is using, not what would give the best odds.
4. **What's the DC?** Set it before the roll is made, never after.

Call for a roll only when **both success and failure are meaningful and possible**. When a clever approach makes failure implausible, let it work without rolling — reward ingenuity over dice luck. Players shouldn't roll without context; they tell you what their character attempts, then you decide if a roll applies.

### The Three D20 Test Types

These are **distinct** — a rule affecting one does not affect the others unless it explicitly says "D20 Tests."


| Type              | Trigger                          | Target             | Natural 1     | Natural 20       |
| ----------------- | -------------------------------- | ------------------ | ------------- | ---------------- |
| **Ability Check** | Active task vs. challenge        | DC (set by DM)     | Not auto-fail | Not auto-success |
| **Saving Throw**  | Reactive resistance to an effect | DC (set by effect) | Not auto-fail | Not auto-success |
| **Attack Roll**   | Striking a target                | Target's AC        | Auto-miss     | Critical Hit     |


Only attack rolls have Critical Hits. A natural 1 on an ability check or save is *not* an automatic failure — it simply adds 1 to the result.

### Anatomy of a Roll

**Roll 1d20** + ability modifier + Proficiency Bonus (if applicable) vs. DC or AC. Always round fractions down.

When a roll has **Advantage**: roll two d20s, use the higher. **Disadvantage**: roll two d20s, use the lower.

- Multiple sources of Advantage or Disadvantage **do not stack** — still only two dice.
- One source of each **exactly cancels** regardless of count — roll one d20.
- Advantage/Disadvantage applies *after* any reroll (e.g., Heroic Inspiration) — the reroll replaces one die, not both.

### Ability Checks in Detail

**Difficulty Classes:**


| DC  | Difficulty        | Interpretation                                            |
| --- | ----------------- | --------------------------------------------------------- |
| 5   | Very Easy         | Skip the roll unless circumstances are unusual            |
| 10  | Easy              | A character with ability 10, no proficiency succeeds ~50% |
| 15  | Medium            | Needs higher score or proficiency for a ~50% chance       |
| 20  | Hard              | Typically needs both                                      |
| 25  | Very Hard         | Exceptional characters only                               |
| 30  | Nearly Impossible | Reserved for legendary feats                              |


For adjacent DCs you can't decide between, pick the harder one — meaningful risk drives better fiction.

**Calculated DCs:** When a task directly opposes another creature's action, set the DC as 8 + that creature's relevant ability modifier + Proficiency Bonus (if proficient). Use this for Stealth vs. Perception, Deception vs. Insight, etc.

**Group Checks:** When the whole group attempts the same task (sneaking past guards, navigating fog), have everyone roll. If more than half succeed, the group succeeds. This prevents one bad roll from derailing the party while keeping tension.

**Passive Checks:** Use a creature's passive score (10 + modifier + Proficiency Bonus if proficient) when you don't want to tip off players by asking for a roll, or when checking for background awareness. Passive Perception is the most common: 10 + Wis modifier (+ Prof if proficient). This is the DC for noticing a hidden creature or object without actively searching.

**Trying Again:** Failing a check doesn't always permit a retry. If the fictional situation hasn't changed, a second attempt carries a meaningful cost or consequence, or simply isn't possible. Avoid the "try again until you succeed" loop.

**Skills with Different Abilities:** Each skill has a default ability, but you may rule a different pairing applies — Intimidation via Strength for a physical display, Athletics via Dexterity for a graceful maneuver. Name the full pairing (e.g., "Strength (Intimidation)") when you call for it.

### Skills Reference


| Skill           | Default Ability | Use                                                |
| --------------- | --------------- | -------------------------------------------------- |
| Acrobatics      | Dex             | Balance, tumbling, tricky movement                 |
| Animal Handling | Wis             | Control, calm, or read animals                     |
| Arcana          | Int             | Magic lore, spell identification, planar knowledge |
| Athletics       | Str             | Climbing, jumping, swimming, grappling, shoving    |
| Deception       | Cha             | Lying, misdirection, disguise                      |
| History         | Int             | Lore, events, lineages, geography                  |
| Insight         | Wis             | Detecting lies, reading motive, sensing attitude   |
| Intimidation    | Cha             | Threats, coercion, hostile pressure                |
| Investigation   | Int             | Clues, deduction, searching for hidden mechanisms  |
| Medicine        | Wis             | Stabilizing the dying, diagnosing poison/disease   |
| Nature          | Int             | Terrain, plants, animals, weather, natural cycles  |
| Perception      | Wis             | Noticing things; drives Passive Perception         |
| Performance     | Cha             | Entertaining an audience                           |
| Persuasion      | Cha             | Convincing through good faith, tact, or appeal     |
| Religion        | Int             | Divine lore, rituals, undead, celestials, fiends   |
| Sleight of Hand | Dex             | Pickpocketing, palming objects, legerdemain        |
| Stealth         | Dex             | Moving quietly, hiding from notice                 |
| Survival        | Wis             | Tracking, foraging, navigation, weather reading    |


### Proficiency

Added to D20 Tests only when the creature has relevant proficiency (skill, tool, weapon, save, spell attack). **Never stacks** — apply the bonus at most once, even if multiple features would grant it.

**Expertise** doubles the Proficiency Bonus for one specific skill. Still doesn't combine with other doubling features.

### Consequences — Beyond Pass/Fail

Don't treat every result as binary. Options:

- **Success at a cost:** The character achieves the goal but suffers a complication — injury, alarm raised, resource spent, worse position.
- **Degrees of failure:** Failure by 5+ triggers a worse outcome than a narrow miss. A narrow miss might mean "not yet" while a large failure triggers a trap or escalation.
- **Degrees of success:** Exceeding the DC by 5+ can yield extra information, faster completion, or a bonus effect.
- **"Yes, and":** When players propose unexpected approaches, accept and add a consequence or twist.
- **"No, but":** When something can't work, block that path while offering a different lead or partial progress. Never a pure dead end.

### Improvising Damage

When an effect causes harm outside normal rules, use this scale:


| Severity | Example                        | Damage                                                     |
| -------- | ------------------------------ | ---------------------------------------------------------- |
| Nuisance | Minor hazard, brief exposure   | 1d10 (level 1–4), 2d10 (5–10), 4d10 (11–16), 10d10 (17–20) |
| Deadly   | Significant threat, could kill | 2d10 (1–4), 4d10 (5–10), 10d10 (11–16), 18d10 (17–20)      |


---

## Part 2: Actions, Bonus Actions, Reactions

### The Action Economy

Each turn: **move** (up to Speed) + **one Action** + **one Bonus Action** (if available). Each round: **one Reaction** (resets at start of your turn). These are independent — using one doesn't consume another. Only one thing at a time: no creature takes two Actions on the same turn except by features that explicitly grant extras.

### Standard Actions


| Action        | Effect                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Attack**    | Make one attack (or more if Extra Attack applies).                                                                                                                                                                                                                                                                                                                                                                   |
| **Dash**      | Gain extra movement equal to Speed this turn.                                                                                                                                                                                                                                                                                                                                                                        |
| **Disengage** | Movement doesn't provoke Opportunity Attacks for the rest of the turn.                                                                                                                                                                                                                                                                                                                                               |
| **Dodge**     | Until start of your next turn: attacks against you have Disadvantage; you have Advantage on Dex saves. Lost if Incapacitated or Speed = 0.                                                                                                                                                                                                                                                                           |
| **Help**      | Give an ally Advantage on their next ability check or attack roll (must be adjacent for attack help). Or use Medicine DC 10 to stabilize a dying creature.                                                                                                                                                                                                                                                           |
| **Hide**      | Dex (Stealth) check vs. DC 15 while Heavily Obscured or behind Three-Quarters/Total Cover, out of every enemy's line of sight. Success → Invisible condition. Ends when: you make noise louder than a whisper, an enemy finds you, you make an attack roll, or you cast a spell with a Verbal component.                                                                                                             |
| **Influence** | Cha (Deception/Intimidation/Performance/Persuasion) or Wis (Animal Handling) check to alter an NPC's attitude.                                                                                                                                                                                                                                                                                                       |
| **Magic**     | Cast a spell, activate a magic item, or use another magical ability.                                                                                                                                                                                                                                                                                                                                                 |
| **Ready**     | Declare a perceivable trigger and a response (an action, or movement up to Speed). When the trigger occurs, use your Reaction to execute. Readied spells are cast now, slot expended, released on trigger — if not released before your next turn, the slot is lost. Ready is preparatory, not binding: you can abandon the readied Reaction to take an Opportunity Attack instead (but you have only one Reaction). |
| **Search**    | Wisdom (Perception) or Intelligence (Investigation) check to find something.                                                                                                                                                                                                                                                                                                                                         |
| **Study**     | Ability check to glean information (Arcana for a magic item, History for a creature's legend, Medicine for a condition's cause).                                                                                                                                                                                                                                                                                     |


### Bonus Actions and Reactions

**Bonus Actions** are available *only* when a feature, spell, or rule explicitly grants one. A Bonus Action cannot substitute for an Action, nor vice versa — they are completely distinct resources.

**Reactions** trigger on specific events. One Reaction per round.

**Opportunity Attack (Reaction):** When a creature you can see **voluntarily leaves your reach** using its action, Bonus Action, Reaction, or Speed — make one melee attack against it. Does *not* trigger when a creature teleports, is moved involuntarily, or uses Disengage. Grapple and Shove use no attack roll and therefore do not trigger effects keyed to "being hit or missed by an attack roll."

---

## Part 3: Social Interaction

### NPC Attitudes


| Attitude        | Mechanical Effect                                                             |
| --------------- | ----------------------------------------------------------------------------- |
| **Friendly**    | Views you favorably. You have Advantage on Charisma checks to influence them. |
| **Indifferent** | Neither hostile nor helpful. No modifier.                                     |
| **Hostile**     | Opposes you. You have Disadvantage on Charisma checks to influence them.      |


Attitude governs starting posture, not absolute compliance. A Friendly NPC can still refuse a dangerous request; a Hostile NPC can still be bargained with under extreme pressure.

### Running Social Encounters

Balance free roleplaying with ability checks — don't call for checks on every exchange, and don't skip them entirely when stakes are real. Some guidance:

- **Don't force checks for things RP already earned.** If a player delivers a compelling argument in-character, reward it without demanding a Persuasion roll.
- **Do call checks when the NPC's resistance is meaningful** and both outcomes are interesting.
- **NPC portrayals:** Identify one or two adjectives that best describe the NPC (e.g., "greedy and cautious," "kind but secretive"). Voice every NPC consistently from those traits; you don't need elaborate backstory for a two-minute encounter.
- **Help Action in social encounters:** One character can assist another's Charisma check — the helper must be able to contribute meaningfully (knows the subject, has standing with the NPC, etc.).

### Influence Action

Make a Charisma (Deception, Intimidation, Performance, or Persuasion) or Wisdom (Animal Handling) check. On success, the attitude shifts one step toward Friendly or the NPC complies with a reasonable request. On failure, don't slam the door — offer partial results, complications, or a changed approach that might work.

---

## Part 4: Exploration

### Vision and Light


| Condition        | Effect                                                            |
| ---------------- | ----------------------------------------------------------------- |
| **Bright Light** | Normal vision.                                                    |
| **Dim Light**    | Lightly Obscured — Disadvantage on sight-based Perception checks. |
| **Darkness**     | Heavily Obscured — effectively Blinded for sight.                 |


**Darkvision:** Treats darkness as dim light within its range. Cannot see color. Does not grant normal vision in dim light.

**Magical Darkness:** Only blocks Darkvision if the specific effect's text says so — the *Darkness* spell explicitly does; generic magical darkness does not.

**Blindsight:** Perceives within range regardless of light or Invisible condition. Finding a hidden creature removes their Hidden status entirely.

**Truesight:** Sees through darkness, Invisible condition, illusions, and into the Ethereal Plane within range.

### Hiding

The **Hide action** requires: a Dex (Stealth) check vs. DC 15, while Heavily Obscured or behind Three-Quarters/Total Cover, out of every enemy's line of sight. Record the check result — it becomes the DC for an enemy's Perception check to find the hidden creature. Success grants the **Invisible condition** while hidden.

**When to call for Perception checks vs. use Passive Perception:** Asking players to roll tips them off that something is there. Use Passive Perception when you don't want to telegraph hidden things. Use active checks when characters are actively searching.

### Perception and Encounter Distance


| Conditions | Audible Range | Visual Range                           |
| ---------- | ------------- | -------------------------------------- |
| Quiet      | 2d6 × 10 ft   | Clear: line of sight                   |
| Noisy      | 2d6 × 50 ft   | Lightly obscured: limited              |
| —          | —             | Heavily obscured (fog, dark): 10–30 ft |


Perception triggers differently by encounter type: noisy groups are heard before they're seen; scouts might spot an ambush that a marching column misses.

### Travel

**Pace and its effects:**


| Pace   | Per Hour | Per Day  | Effect                   |
| ------ | -------- | -------- | ------------------------ |
| Fast   | 4 miles  | 30 miles | −5 to Passive Perception |
| Normal | 3 miles  | 24 miles | —                        |
| Slow   | 2 miles  | 18 miles | Can use Stealth          |


**Journey Stages:** Break longer trips into 2–3 stages, each representing a distinct leg with its own challenges. Unimportant travel can be glossed over in a sentence. Each stage can feature one challenge: a creature encounter, a foraging roll, navigation hazard, obstacle, or search opportunity. Don't force all categories — pick what fits the fiction.

### Hazards


| Hazard            | Rule                                                                                                                                                           |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Falling**       | 1d6 Bludgeoning per 10 feet, max 20d6. Lands Prone unless takes 0 damage. DC 15 Str(Athletics) or Dex(Acrobatics) to halve damage falling into liquid.         |
| **Suffocation**   | Hold breath for 1 + Con modifier minutes (min 30 sec). After that, drop to 0 HP at start of each turn.                                                         |
| **Dehydration**   | 1 day without water → gain 1 Exhaustion level per hour thereafter until drinking.                                                                              |
| **Malnutrition**  | 3 + Con modifier days without food → 1 Exhaustion level per day.                                                                                               |
| **Extreme Cold**  | 0°F or below → DC 10 Con save per hour or gain 1 Exhaustion level. Immunity: cold resistance, cold immunity, appropriate gear.                                 |
| **Extreme Heat**  | Very hot conditions → DC 5 Con save per hour (DC rises by 1 each hour) or gain 1 Exhaustion level. Immunity: fire resistance, fire immunity, appropriate gear. |
| **High Altitude** | Above 10,000 ft without acclimatization → Exhaustion after 1 hour; Disadvantage on Str/Con checks and saves.                                                   |
| **Deep Water**    | Deeper than 100 ft without Swim Speed → DC 10 Con save per hour or gain 1 Exhaustion level.                                                                    |


### Environmental Effects


| Effect              | Mechanical Rule                                                                                                |
| ------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Slippery Ice**    | Difficult Terrain. Walking requires DC 10 Acrobatics or fall Prone.                                            |
| **Strong Wind**     | Disadvantage on ranged attack rolls. Concentration checks for spells with Verbal components may be warranted.  |
| **Thin Ice**        | Crack threshold: 3d10 × 10 lbs. Heavier creatures break through — falling into icy water starts cold exposure. |
| **Dead Magic Zone** | As Antimagic Field spell — permanent, typically ≤300 ft diameter. All magic ceases.                            |
| **Wild Magic Zone** | Spellcasting triggers a Wild Magic surge (roll on the relevant table).                                         |


---

## Part 5: Combat

### Starting Combat

Combat starts when — and only when — you say it does. Don't let players roll Initiative by fiat; some class features trigger on Initiative rolls, and you control that moment. If a character initiates hostilities (casting a spell, making an attack), give them Advantage on their Initiative roll.

### Initiative

Roll 1d20 + Dexterity modifier. Higher result acts first. **You cannot delay your turn** — if a player wants to act later in response to something, they take the Ready action. Ties: DM decides (or use Dex score as tiebreaker, or act simultaneously).

**Initiative Score (optional, faster):** Use 10 + Dex modifier as a fixed score instead of rolling. +5 if the creature would have Advantage; −5 for Disadvantage. Good for monsters when you want to skip the roll.

**Surprise:** A creature that doesn't notice combat beginning has Disadvantage on its Initiative roll. Surprise is not a skipped turn — just a disadvantaged roll.

### On Each Turn

In any order: **move** (up to Speed, can split before/after actions) + **one Action** + **one Bonus Action** (if available). Free: talking, gesturing, dropping an item.

### Movement

- **Difficult Terrain:** 2 feet of movement per foot traversed. Does not stack — always costs 2 ft/ft.
- **Dropping Prone:** Free. Standing up costs half your Speed.
- **Passing through spaces:** You can move through an ally's, Incapacitated creature's, Tiny creature's, or a creature 2+ sizes different from yours. You cannot willingly **end** your move in another creature's space.
- **Diagonal movement (grid):** Count every other diagonal as 2 squares (1–2–1–2 rule), or simply count each as 1 for simplicity — decide consistently.

### Creature Size and Space


| Size           | Grid Space                   |
| -------------- | ---------------------------- |
| Tiny           | 2.5 × 2.5 ft (¼ square)      |
| Small / Medium | 5 × 5 ft (1 square)          |
| Large          | 10 × 10 ft (2 × 2 squares)   |
| Huge           | 15 × 15 ft (3 × 3 squares)   |
| Gargantuan     | 20 × 20 ft+ (4 × 4 squares+) |


### Making an Attack

1. Choose target within range.
2. Apply Advantage/Disadvantage (conditions, cover, range, melee with ranged).
3. Roll attack; compare to AC.
4. On hit, roll damage.

**Ranged attacks:** Normal range / long range listed as "X/Y ft." Attacking beyond normal range up to long range imposes Disadvantage. Attacking beyond long range is impossible. Attacking while a **hostile creature is adjacent** imposes Disadvantage on ranged attacks.

**Melee attacks:** Default reach 5 feet; some weapons/features extend to 10 feet.

**Line of Sight:** Trace an imaginary line from any corner of your space to any part of the target's space. If the line passes through or touches a vision-blocking object, you lack line of sight. No line of sight = can't target directly.

### Opportunity Attacks

Triggered when a creature you can see **voluntarily leaves your reach** (using action, Bonus Action, Reaction, or Speed). Use your Reaction to make one melee attack. Does *not* trigger on teleportation, involuntary movement, or Disengage. If you hold a readied Reaction and an OA opportunity arises, choose one — taking the OA consumes your Reaction and the readied action is lost.

### Cover


| Cover                    | Bonus                      |
| ------------------------ | -------------------------- |
| **Half Cover**           | +2 to AC and Dex saves     |
| **Three-Quarters Cover** | +5 to AC and Dex saves     |
| **Total Cover**          | Can't be directly targeted |


An intervening creature grants the target **Half Cover (+2 AC)** — it does *not* impose Disadvantage on the attacker's roll.

### Mounted Combat

**Controlled mount** (trained): Initiative changes to match rider's; can only Dash, Disengage, or Dodge; moves on rider's turn. **Independent mount:** keeps own Initiative, acts freely. If mount is moved involuntarily or knocked Prone, rider makes DC 10 Dex save or falls off (Prone, up to 5 feet away).

### Underwater Combat

Melee weapons without Thrown property have Disadvantage unless attacker has Swim Speed. Ranged weapon attacks (not crossbows) have Disadvantage and auto-miss at long range. No Swim Speed → water is Difficult Terrain.

### Running Combat Well

**Narrate enemy actions clearly.** Players need to know what monsters are doing — both fictionally and mechanically. Describe the Dash as "your foe sprints across the room," the Ready as "your foe watches you, coiled to react." When a monster casts a spell, describe the Verbal chanting, Somatic gestures, or Material component use so players can recognize spellcasting and potentially react (Counterspell, etc.).

**Share information as it becomes apparent.** When a Fire Bolt hits a Fire Elemental and does nothing, tell the players the spell didn't seem to bother it at all — let them reason from what their characters experience.

**Don't repeat game states.** If a character Disengages to create distance, don't immediately erase that effort by having the same monsters chase them down. Move the threats somewhere else — escalate, don't reset.

**Hasten a certain outcome.** If victory is clearly inevitable and the combat is dragging, simply have the last monster drop. Players don't need to know it had 15 HP left.

**Adjust difficulty mid-fight if needed** — not by cheating on dice, but by: having monsters flee when bloodied, calling in reinforcements, changing the terrain, or having a monster switch tactics entirely.

**Monsters are characters with goals.** They don't "attack the nearest enemy" by default — they pursue their objectives. The cornered captain grabs a hostage; the losing minions break and run; the intelligent undead makes a tactical retreat to a chokepoint. Sapient monsters might parley mid-combat if the tide turns; if both sides agree to talk, suspend the Initiative order for negotiation. If talks fail, resume.

### Mobs

When running large groups of identical monsters, use these shortcuts:

- Use **average damage** from the stat block instead of rolling.
- If a spell/attack reduces a monster to a handful of HP, assume it's eliminated — don't track exact totals.
- **Divide into mobs of 5–8** identical creatures; spread their turns between character turns. Never more mobs than characters.
- **Average results:** To determine how many of a mob succeed on a D20 Test without rolling: find the minimum roll needed to succeed, look up the percentage in the Mob Results table, apply that fraction to the mob count. (E.g., 10 orcs need a 15+; only 30% of d20 rolls are 15+; so ~3 succeed.)

### Chases

Normal movement rules make chases mechanical and predictable. Use the chase rules instead:

- Roll Initiative when the chase begins. Each participant moves and acts each turn.
- Track distance between quarry and pursuers instead of exact positions.
- **Dashing:** A creature can Dash repeatedly, but after two consecutive Dashes, it must make a DC 10 Constitution check or gain 1 Exhaustion level.
- Each round, roll on a Chase Complications table (urban or wilderness) to introduce obstacles — crowds, low branches, icy cobblestones, sudden drops.
- The quarry **escapes** when: distance exceeds pursuit range, they're out of sight for 3 consecutive rounds (requiring 3 consecutive DC 15 Perception or Survival checks to reacquire), or they enter a space the pursuer can't follow.
- The pursuer **catches up** when distance closes to melee reach.

---

## Part 6: Damage and Healing

### Hit Points

HP represents durability and will to live. Loss has **no mechanical effect on capabilities** until HP reaches 0. Current HP ranges from 0 to maximum.

**Bloodied:** At or below half HP maximum. No mechanical effect by itself, but:

- Narrate it visibly ("the guard is clearly flagging, blood seeping through her armor").
- Some monster abilities and features trigger on the Bloodied state.
- Signals to attentive players that a creature is in real trouble.

### Damage Rolls

Roll the damage dice specified by the weapon or effect. For weapons, add the relevant ability modifier. Most spell damage rolls *don't* add an ability modifier unless the spell text says so.

**Critical Hit** (natural 20 attack roll): Roll **all** damage dice twice — don't just double the total. Add modifiers once. Apply to both weapon damage and any additional dice (e.g., Sneak Attack dice are also doubled).

**Saving throw damage:** On a failed save, full damage. On a success, half damage (divide total by 2, round down) — unless the effect says "no damage on a successful save."

### Damage Types

Acid, Bludgeoning, Cold, Fire, Force, Lightning, Necrotic, Piercing, Poison, Psychic, Radiant, Slashing, Thunder. Types have no inherent rules — they matter only in context of Resistance, Immunity, or Vulnerability.

### Resistance, Immunity, Vulnerability

- **Resistance:** Halve damage of that type (round down). Applied once per instance regardless of how many sources of Resistance apply. Damage can be reduced to 0 but not below.
- **Immunity:** Take no damage of that type, or in the case of a condition, are unaffected by it.
- **Vulnerability:** Double damage of that type.
- **Order when multiple apply:** Vulnerability first (×2), then Resistance (÷2) — net result is normal damage. They don't cancel each other.

### Healing

Restores current HP up to (not exceeding) maximum. Cannot heal a dead creature. Healing and damage occurring simultaneously (e.g., simultaneous trigger effects) are resolved separately, not added together.

### Dropping to 0 HP

**Instant Death:** If damage from a single hit reduces HP to 0 and the leftover damage equals or exceeds HP maximum, the creature dies instantly.

**Falling Unconscious:** Otherwise, creature gains the Unconscious condition and begins making **Death Saving Throws** at the start of each of its turns.

**Death Saving Throws:** Roll 1d20, no modifiers.

- 10+ = success; 9 or lower = failure.
- 3 successes → stable.
- 3 failures → dead.
- Natural 20 → immediately regain 1 HP (conscious, Prone).
- Natural 1 → counts as 2 failures.
- Taking any damage while at 0 HP → 1 death save failure. A Critical Hit → 2 failures.
- Any healing (any amount) → HP restored, process ends.

**Stabilizing:** Help action + DC 10 Wisdom (Medicine) → creature is stable. No longer makes death saves. Regains 1 HP after 1d4 hours.

**Knocking Out:** When a melee attack would reduce a target to 0 HP, attacker may choose to knock out instead → drops to 0 HP, Unconscious, begins a Short Rest. Revived by any HP restoration or DC 10 Wis (Medicine).

### Temporary Hit Points

Separate pool. Damage depletes Temp HP first, then HP. **Do not stack** — take the higher of existing vs. new grant. Healing does not restore Temp HP. Not real HP or healing — spells/features that trigger on healing do not trigger from Temp HP.

### Death in Play

**Death must be fair.** Don't single a character out or fudge dice against them. Consider rolling in the open during high-lethality moments so players see you aren't cheating in the monsters' favor. Don't punish a character for a player's behavior at the table.

**Scaling lethality:** Choose your approach and hold it. Options: monsters always deliver killing blows (high lethality), they knock unconscious rather than kill (cinematic lethality), or they capture instead of kill (story-preserving). Tell the players your default early; deviating from it mid-campaign for a specific character will feel targeted.

**Death scenes:** When a character does die, give the moment weight — a final action, a last word, a dramatic consequence. Don't rush past it. But also don't dwell so long that it becomes misery tourism.

**If everyone dies:** Options — the villain captures the party (they wake imprisoned), a deity intervenes (divine council requiring a quest), escape from the underworld, or a fresh start with new characters who inherit the consequences of the fallen ones.

---

## Part 7: Conditions

Conditions are binary (you have it or you don't) except Exhaustion. Multiple applications of the same condition share the longest duration — effects don't compound. To remove a condition: meet its counter (stand up for Prone, end Concentration for Incapacitated via that route) or let the effect expire.

### Condition Reference

**Blinded** — Can't see; auto-fail sight-based checks. Attacks against you: Advantage. Your attacks: Disadvantage.

**Charmed** — Can't attack the charmer or target them with harmful effects. Charmer has Advantage on social ability checks with you.

**Deafened** — Can't hear; auto-fail hearing-based checks.

**Exhaustion** — Cumulative levels 1–5; death if level would exceed 5. Each Long Rest reduces by 1.


| Level | Effect                                         |
| ----- | ---------------------------------------------- |
| 1     | Disadvantage on all d20 Tests                  |
| 2     | Speed halved                                   |
| 3     | Disadvantage on attack rolls and saving throws |
| 4     | HP maximum halved                              |
| 5     | Speed = 0                                      |


**Frightened** — Disadvantage on ability checks and attack rolls while source of fear is within line of sight. Can't willingly move closer to the source. Note: Disadvantage applies even if the source is imperceptible, as long as you have line of sight to its space.

**Grappled** — Speed = 0 (can't increase). Disadvantage on attacks against targets other than the grappler. Grappler can drag/carry you — costs 1 extra ft per ft moved unless you're Tiny or 2+ sizes smaller. A grappler who falls Prone does *not* make the grappled creature Prone.

**Incapacitated** — Can't take Actions, Bonus Actions, or Reactions. Breaks Concentration. Can't speak.

**Invisible** — Not affected by effects requiring sight unless the perceiver can see the creature. Attacks against you: Disadvantage. Your attacks: Advantage. If Invisible when rolling Initiative: Advantage on the roll.

**Paralyzed** — Has Incapacitated. Speed = 0. Auto-fail Str and Dex saves. Attacks against you: Advantage. **All hits within 5 feet are Critical Hits.**

**Petrified** — Transformed into inanimate solid. Has Incapacitated. Speed = 0. Auto-fail Str and Dex saves. Attacks against you: Advantage. Resistance to all damage. Immune to Poisoned condition.

**Poisoned** — Disadvantage on attack rolls and ability checks.

**Prone** — Movement by crawling only (costs double Speed). Attacks against you from within 5 feet: Advantage; from beyond 5 feet: Disadvantage. Your melee attacks: Disadvantage. Counter: stand up by spending half Speed.

**Restrained** — Speed = 0. Your attacks: Disadvantage. Attacks against you: Advantage. Disadvantage on Dex saves.

**Stunned** — Has Incapacitated. Speed = 0. Auto-fail Str and Dex saves. Attacks against you: Advantage. Note: Stunned intentionally no longer prevents movement in 2024 rules — Speed 0 still pins the creature in practice, but Paralyzed is the harder version (all hits are Crits).

**Unconscious** — Has Incapacitated. Speed = 0. Falls Prone. Auto-fail Str and Dex saves. Attacks against you: Advantage. **All hits within 5 feet are Critical Hits.** Unaware of surroundings.

### Fear and Mental Stress

Use the **Frightened condition** as the baseline for supernatural fear. Baseline: Wisdom saving throw, DC calibrated by how terrifying the situation is.


| Situation                                                    | Fear DC |
| ------------------------------------------------------------ | ------- |
| Harmless apparition in a sarcophagus                         | 10      |
| Magical trap creates illusory manifestation of greatest fear | 15      |
| Party faces a CR 13+ undead for the first time               | 20      |
| Witnessing a god's true form                                 | 25      |


**Mental Stress:** For psychically or cosmically overwhelming encounters, consider imposing a short-term effect (roll on the Mental Stress table) in addition to or instead of the Frightened condition. Effects last minutes to hours. Prolonged exposure can impose Exhaustion. Discuss with players before using mental stress mechanics — they can be uncomfortable.

Discuss fear/stress mechanics with players before using them in your campaign.

---

## Part 8: Resting

### Short Rest

At least 1 hour of light activity. Spend any number of Hit Point Dice (roll each + Con modifier) to regain HP. Must have at least 1 HP to begin. No hard daily limit — DM controls pacing by controlling when safe downtime is available.

### Long Rest

At least 8 hours: 6 hours sleep (Unconscious condition during sleep), no more than 2 hours light activity. Must have at least 1 HP to begin. Cannot start another Long Rest until 16 hours have passed.

**Benefits on completion:** All lost HP restored. All spent Hit Point Dice restored. Exhaustion level reduced by 1. Ability scores reduced by effects return to normal. Most class features recharge.

---

## Part 9: NPCs

### Building a Memorable NPC

Flesh out only NPCs with prominent roles. For everyone else, one or two physical or behavioral details are enough — the innkeeper with the ear missing, the guard who talks while eating. Don't write three pages of backstory for an NPC whose scene will last three minutes.

For prominent NPCs, define:

- **Stat block:** Use an existing Monster Manual block (often Mage, Guard, Noble, Thug, etc.) with tweaks.
- **Alignment:** Use it as a shorthand for moral/ethical posture — actions reveal alignment, not declarations.
- **Personality:** One or two adjectives derived from alignment and highest/lowest ability scores.
- **Appearance:** One or two distinctive physical details.
- **Secret:** What the NPC is hiding or pursuing that the party doesn't know.

### NPC Alignment Posture

Alignment is a *roleplaying tool*, not a straitjacket. A creature can act against type — that's a character choice, not a rules violation. Actions over time reveal alignment; what a creature *professes* and what it *does* may diverge. Monster stat blocks list alignment as a default posture for a typical specimen; individual monsters can differ.

### Recurring NPCs

NPCs who reappear across multiple sessions create the sense of a living world. Let a recurring villain grow — use a different stat block each time to reflect their advancement. Don't overdo NPC development upfront; add detail as the NPC earns it through play.

### NPCs as Party Members

When an NPC joins the party, track their **Loyalty score** (0–10). Loyalty shifts based on: how the party treats them, whether the party honors commitments, whether the NPC's goals align with the party's current actions.


| Loyalty | Behavior                                  |
| ------- | ----------------------------------------- |
| 10      | Fights to the death for the party         |
| 8–9     | Loyal, follows dangerous orders           |
| 5–7     | Reliable but won't take suicidal risks    |
| 3–4     | Wavering; looking for a better situation  |
| 1–2     | Actively looking to leave or betray       |
| 0       | Leaves or betrays at earliest opportunity |


---

## Part 10: Challenge Rating and Encounter Difficulty

**CR** calibrates a monster's threat level for **four player characters at full resources**. Compare CR to party level:

- CR ≈ party level → meaningful challenge.
- CR significantly higher → dangerous; may require tactics, resources, or escape.
- CR significantly lower → likely trivial.

Adjust for: party size (fewer PCs → harder), tactical context, how many resources the party has already spent today, whether monsters have action-economy advantages (many small enemies vs. one big one), and terrain.

**Character Advancement:**

- **XP:** Award for defeated enemies and completed noncombat challenges (DMG has XP tables by CR).
- **Milestone:** Level up when characters complete a meaningful story goal — simple, no tracking.
- **Session-based:** Level up every N sessions regardless of events — simplest.
- Use whichever method fits your campaign; all are valid.

---

## Part 11: Key Glossary

**Armor Class (AC):** Number an attack must meet or beat to hit.

**Attunement:** Up to 3 magic items may be attuned at once. Attunement requires a Short Rest focusing on the item. Non-attuned magic items with attunement requirements don't function.

**Bloodied:** At or below half HP maximum. Narrate visibly.

**Cantrip:** A spell requiring no spell slot. Scales by character level.

**Challenge Rating (CR):** Calibrated for 4 PCs at full resources. See Part 10.

**Concentration:** Maintains ongoing spell effects. Only one Concentrated spell active at a time. Taking damage requires a Con save (DC = max of 10 or half damage taken) to maintain. Incapacitated breaks Concentration automatically.

**Critical Hit:** Natural 20 on attack roll. All damage dice rolled twice; modifiers added once.

**D20 Test:** Umbrella term for ability checks, attack rolls, and saving throws. A rule affecting "D20 Tests" affects all three.

**Difficult Terrain:** 2 ft of Speed per foot traversed.

**Expertise:** Double Proficiency Bonus on one specific skill.

**Heroic Inspiration:** Spend to reroll any single die immediately after rolling; must use new result. Can't stockpile; give excess to another PC.

**Hit Point Dice (HD):** Class-defined dice used during Short Rests to recover HP.

**Initiative:** Turn order in combat. 1d20 + Dex modifier.

**Opportunity Attack:** Reaction-triggered melee attack when creature voluntarily leaves your reach.

**Passive Perception:** 10 + Wis modifier (+ Prof if proficient). Used when a creature might notice something without actively searching.

**Per Day:** A feature that recharges "per day" recharges on a Long Rest, not at midnight.

**Proficiency Bonus:** Added once to D20 Tests where proficiency applies. Never stacks.

**Reach:** Default melee reach 5 ft. Some weapons/features extend to 10 ft.

**Resistance:** Halve damage of the specified type (round down).

**Ritual:** Some spells cast as rituals: 10 minutes longer, no spell slot consumed.

**Round:** ~6 seconds of game time. All participants take one turn.

**Simultaneous Effects:** When two effects happen at the same moment, the affected creature (or their controller) chooses the order of application.

**Speed:** Distance (feet) a creature can move on its turn. Multiple Speed types may exist (Walk, Fly, Swim, Burrow, Climb).

**Stable:** A creature at 0 HP no longer making death saves. Still Unconscious until healed.

**Temporary Hit Points:** Buffer HP absorbing damage first. Does not stack; not real HP; not affected by healing.

---

