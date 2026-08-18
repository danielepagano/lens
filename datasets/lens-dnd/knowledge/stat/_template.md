<!-- D&D creature stat block (2024 layout). Usage: the sheet for a creature the AI controls; also the target shape when authoring a custom one. See rules.stat for how one is used at the table, design.stat for how to build one. -->
Creature Name · Size Type, Alignment

Every stat block in this dataset uses the layout below. A custom block that departs from it reads as a different kind of object to whoever runs it, so match it:

```
**Creature Name** · Medium Humanoid, Neutral Evil

**AC** 15 · **HP** 45 · **Speed** 30 ft.

| STR | DEX | CON | INT | WIS | CHA |
|-----|-----|-----|-----|-----|-----|
| 14 (+2) | 16 (+3) | 14 (+2) | 11 (+0) | 12 (+1) | 10 (+0) |

**Skills** Perception +3, Stealth +5
**Senses** Darkvision 60 ft.,  Passive Perception 13
**Languages** Common, Thieves' Cant
**CR** 3

Trait Name. Always-on abilities go here, unheaded, before the first divider.

---
**Actions**

Multiattack. What one Action buys.

Attack Name. Melee Attack Roll: +5, reach 5 ft. Hit: 7 (1d8 + 3) Piercing damage.

---
**Reactions**

Reaction Name. Trigger: what sets it off. Response: what happens.

---
**Description**

One or two paragraphs: what this creature is, how it behaves, what people know about it.
```

- **HP** is a single number here because this dataset's import drops the dice; the published blocks do print them, and the total is always the same arithmetic: hit dice for the size (Tiny d4, Small d6, Medium d8, Large d10, Huge d12, Gargantuan d20), averaged, plus the CON modifier once per die, rounded down at the end. Writing the expression as `**HP** 97 (15d8 + 30)` is welcome; writing a total no dice count can produce is not.
- The lines under the ability table, in this order: **Saving Throws** (proficient saves only, each one the ability modifier plus PB), **Skills** (omit when it has none), **Immunities** and **Resistances** (only when it has them), **Senses**, **Languages**, **CR**. Published blocks carry saves in a column of the ability table that this dataset's import drops, so most stored blocks show none — that is a gap in the import, not a convention to copy.
- Optional sections, in this order after Actions: **Bonus Actions**, **Reactions**, **Legendary Actions**. Each preceded by a `---` divider. Omit any the creature does not have.
- Damage expressions print the average and the dice, and the average matches the dice.
- No current hit points, conditions, or expended resources — the block is the sheet, never the state of a fight. That is a `tracker.*`.

Tags for finding stat blocks (use with `lens kb with-tag <tag>`):

- **cr (challenge rating):** `cr:0`, `cr:1`, `cr:2`, … `cr:25`, and fractional `cr:1-2`, `cr:1-4`, `cr:1-8` (slash encoded as hyphen)
- **type:** for a swarm, the whole thing is the type (`type:swarm-of-tiny-beasts`, `type:swarm-of-medium-fiends`); otherwise `type:aberration`, `type:beast`, `type:celestial`, `type:construct`, `type:dragon`, `type:elemental`, `type:fey`, `type:fiend`, `type:giant`, `type:humanoid`, `type:monstrosity`, `type:ooze`, `type:plant`, `type:undead`
- **size:** `size:tiny`, `size:small`, `size:medium`, `size:large`, `size:huge`, `size:gargantuan`
- **habitat:** `habitat:arctic`, `habitat:coastal`, `habitat:desert`, `habitat:forest`, `habitat:grassland`, `habitat:hill`, `habitat:mountain`, `habitat:swamp`, `habitat:underdark`, `habitat:underwater`, `habitat:urban`, `habitat:any`; planar: `habitat:planar-abyss`, `habitat:planar-acheron`, `habitat:planar-astral-plane`, `habitat:planar-beastlands`, `habitat:planar-elemental-chaos`, `habitat:planar-elemental-plane-of-air`, `habitat:planar-elemental-plane-of-earth`, `habitat:planar-elemental-plane-of-fire`, `habitat:planar-elemental-plane-of-water`, `habitat:planar-elemental-planes`, `habitat:planar-ethereal-plane`, `habitat:planar-feywild`, `habitat:planar-gehenna`, `habitat:planar-limbo`, `habitat:planar-lower-planes`, `habitat:planar-mechanus`, `habitat:planar-nine-hells`, `habitat:planar-shadowfell`, `habitat:planar-upper-planes`

<!-- TAG POLICY: a custom block must carry `cr:`, `type:`, and `size:` — `cr:` is read for XP by balance_encounter, and a missing one silently counts as 0. Add `habitat:` when it helps a later search. You may link the `npc.*` whose sheet this is. Do not tag any spell used, and any equipment used needs to be self-contained in the stat block. -->
