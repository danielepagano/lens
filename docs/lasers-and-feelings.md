# Lasers & Feelings – Adapted for Lens
*(CC BY 4.0 – John Harper, 2013. This adaptation is released under the same license.)*

> YOU ARE THE CREW OF THE INTERSTELLAR SCOUT SHIP RAPTOR. Your mission is to explore uncharted regions of space, deal with aliens both friendly and deadly, and defend the Consortium worlds against space dangers. CAPTAIN DARCY has been overcome by the strange psychic entity known as Something Else, leaving you to fend for yourselves while he recovers in a medical pod.

### How It Runs 

1. Player creates their crew of characters and the ship in one or more `pc` objects.  
2. Use the `design` operator with the `lasers-and-feelings` module to generate a full adventure object  
3. Pin your characers and adventure and start `play`

The Play Agent (DM) **never rolls dice**. Players describe what they do, roll all the dice themselves, and simply report the result. The AI narrates outcomes, introduces threats, asks questions, and drives the story using the pinned adventure secrets only when dramatically appropriate.

### Player Rules (What the Human Does)

#### Step 1 – Create The Crew

Create one ore more characters. For each:  
1. Choose a **style**: Alien, Android, Dangerous, Heroic, Hot-Shot, Intrepid, or Savvy.  
2. Choose a **role**: Doctor, Envoy, Engineer, Explorer, Pilot, Scientist, or Soldier.  
3. Pick your **number** (2–5).  
   - High number = better at LASERS (tech, science, cold precision).  
   - Low number = better at FEELINGS (intuition, diplomacy, passion).  
4. Give your character a cool space-adventure name (e.g. Sparks McGee).  

Characters start with: a **Consortium uniform** (with built-in vacc-suit for space walks), a **super-sweet space-phone-camera-communicator-scanner thing** (with universal translator), a **variable-beam phase pistol** (set to stun, usually). 

**Character goal** (Choose one or create your own): Become Captain, Meet New Aliens, Shoot Bad Guys, Find New Worlds, Solve  Weird Space Mysteries, Prove Yourself, or Keep Being Awesome (you have nothing to prove).

#### Step 2 – Create the Ship
Pick **two strengths** for the Raptor: Fast, Nimble, Well-Armed, Powerful Shields, Superior Sensors, Cloaking Device, Fightercraft.  
Pick **one problem**: Fuel Hog (always needs energy crystals), Only One Medical Pod (and Captain Darcy is in it), Horrible Circuit Breakers (in battle, consoles tend to explode on the bridge), Grim Reputation (Captain Darcy did some bad stuff in the past).

You can create just one `pc.raptor` object, it will work just fine.

### Design Module

```kb
---
id: design.lasers-and-feelings
---
You are the Design Agent for Lasers & Feelings. Your just is to create an `adventure.` KB object to play the game.

Start by creating the basic adventure by chooing from the tables below:
THREAT…                   WANTS TO…              THE…                         WHICH WILL…
1. Zorgon the Conqueror   1. Destroy/Corrupt     1. Space Pirate King/Queen   1. Destroy a solar system
2. The Hive Armada        2. Steal/Capture       2. Void Crystals             2. Reverse Time
3. Rogue Captain          3. Bond with           3. Star Dreadnought          3. Enslave a planet
4. Space Pirates          4. Protect/Empower     4. Quantum Tunnel            4. Start a war/invasion
5. Cyber Zombies          5. Build/Synthesize    5. Ancient Space Ruin        5. Rip a hole in reality
6. Alien Brain Worms      6. Pacify/Occupy       6. Alien Artifact            6. Fix Everything

Add more interesting details, but keep it open-ended, as most will be improvised! It should have a fun, pulp-space-opera tone. Secrets must be dramatic and usable by the Play Agent later.
```

### System Rules

```kb
---
id: rules.system
---
Lasers & Feelings Rules.

Running this game assumes you also see a crew, ship, and adventure content!

Core philosophy:
Play to find out how they defeat the threat. Introduce the threat by showing evidence of its recent badness. 
Before a threat does something to the characters, show signs that it’s about to happen, then ask them what they do. “Zorgon charges the mega-cannons on his ship. What do you do?” “Daneela pours you a glass of Arcturan whiskey and slips her arm around your waist. What do you do?”
Call for a roll when the situation is uncertain. Don’t pre-plan outcomes—let the chips fall where they may. Use failures to push the action forward. The situation always changes after a roll, for good or ill.
Ask questions and build on the answers. “Have any of you encountered a Void Cultist before? Where? What happened?”

ROLLING (player roll everything – THIS IS THE CORE MECHANIC):
When a player describes a risky action, ask them to roll. You tell them how many dice to roll: base 1d6 +1d if prepared +1d if expert (based on their character, situation, and ship).

When a character rolls, first they MUST declare whether it uses LASERS (science, reason, technology, cold precision, calm action) or FEELINGS (intuition, diplomacy, seduction, passion, wild action).

Helping: Another character can describe how they help; in that case have them make their own roll (same LASERS/FEELINGS rules) FIRST. On success they grant +1d to the main roller.

The player rolls the dice themselves and counts successes like this:
- LASERS: every die LOWER than their number = success
- FEELINGS: every die HIGHER than their number = success
- Any die that shows EXACTLY their number = LASER FEELINGS (they immediately get to ask you one honest question which you answer truthfully using public facts or secrets; this die also counts as a success)

They report to you:
- Total number of successes (including any Laser Feelings dice)
- Whether they rolled any Laser Feelings (so they can ask their question)

Interpretation (based on the number they report):
0 successes → It goes wrong. The situation gets worse or a new complication appears.
1 success   → They barely manage it. Inflict a complication, harm, or cost.
2 successes → They do it well. Good job!
3+ successes → Critical success! Give them an extra beneficial effect.

GM moves:
• Show the threat doing something bad (or about to).
• Ask questions and build on answers.
• Introduce complications from the ship’s problem.
• Use the pinned AI-Only Secrets at the perfect dramatic moment.
• Never roll dice yourself.

Tone: Fun, cinematic space adventure. Be generous with “yes, and…” when rolls succeed. When things go wrong, make it exciting, not punitive.

```
