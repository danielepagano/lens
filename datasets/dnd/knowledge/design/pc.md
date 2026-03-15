<!-- Design workflow: Player Character setup. Pin this to help structure a PC object from a character sheet. -->
PLAYER CHARACTER SETUP

Help the user create a `pc.*` object from their character sheet. The goal is NOT to transcribe the character sheet — it's to capture what the AI needs to describe and voice this character during play.

Fetch `pc._template` first. Then ask the user about their character.

WHAT TO CAPTURE:
- Name, nicknames, how others address them
- Appearance: species, gender presentation, physique, distinguishing features, visible equipment, how they move and talk
- Context: background, goals, motivations, personal struggles — but BRIEF. Enough to flavor interactions, not a biography
- How they solve problems: key strengths and weaknesses, passive features the DM needs to know (darkvision, high passive perception, movement speeds, etc.)
- Affiliations: factions, important relationships

WHAT TO LEAVE OUT:
- Full power lists, spell lists, ability scores — the player activates these during play
- Detailed backstory — it biases the AI to reference it constantly
- Internal thoughts and feelings — the player controls when these surface
- Inventory — tracked by the player

The tension is: enough detail that the AI writes the character distinctively ("Alice deftly jumped the narrow wall to get a good angle as she notched her arrow") but not so much that it over-references details ("Alice thought about her troubled childhood at the orphanage as she notched her arrow").

TAGGING:
- ALWAYS tag with `level:N` (total character level) for encounter balancing
- Link to any faction the PC belongs to
- The user can add mechanical condition tags during play (e.g. `speed:flying`, `concentrating`)

Ask the user to describe their character conversationally. Then propose a `pc.*` object and iterate until it feels right.
