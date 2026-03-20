# [DESIGN MODULE]: PLAYER CHARACTER

Help the user create TWO objects from their character: `pc.<name>` for play and `lore.<name>` for planning depth. These serve completely different purposes and must be kept separate.

Fetch `pc._template` and `lore._template` first. Possibly fetch what the user has so far (`kb_get` for the character name). Then ask the user about their character.

PHASE 1: THE PLAY SURFACE (`pc.<name>`)
This object is what the AI needs to describe and voice the character during play. It is pinned in EVERY play interaction, so every word costs tokens.

Ask the user to describe their character conversationally. Then build:
- Name, nicknames, how others address them
- Appearance: species, gender presentation, physique, distinguishing features, visible equipment, how they move and talk
- Context: relevant background, goals, motivations — but BRIEF. Enough to flavor interactions, not a biography
- How they solve problems: key strengths and weaknesses, passive features the DM needs to know (darkvision, high passive perception, movement speeds, etc.)
- Affiliations: factions, important relationships

What to LEAVE OUT of `pc.<name>`:
- Full power lists, spell lists, ability scores — the player activates these during play
- Detailed backstory — it biases the AI to reference it constantly
- Internal thoughts and feelings — the player controls when these surface
- Inventory — tracked by the player
- Emotional wounds, flaws, secret desires — these go in the lore object

The tension: enough detail that the AI writes distinctively ("Alice deftly jumped the narrow wall to get a good angle as she notched her arrow") but not so much that it over-references details ("Alice thought about her troubled childhood at the orphanage as she notched her arrow").

TAGGING: ALWAYS tag `pc.<name>` with `level:N` (total character level) for encounter balancing. Link to any faction the PC belongs to. The user can add mechanical condition tags during play (e.g. `speed:flying`, `concentrating`).

PHASE 2: THE PLANNING DEPTH (`lore.<name>`)
This object contains everything about the character that informs how the STORY evolves — the material that design modules (especially `design.front`) use to create content that resonates with this character. It is NEVER pinned during play.

Probe conversationally for:
- Full backstory: origin, formative events, key relationships from the past
- Emotional wounds: what has hurt them, what they haven't processed
- Flaws: not quirks, but genuine weaknesses of character — pride, cowardice, self-deception, cruelty they justify
- Secret wants: what they desire but won't admit, even to themselves
- Lines they won't cross: moral boundaries — and what might make them cross one anyway
- Misconceptions: things they believe that aren't true, about themselves or the world
- What they're running from, or toward

The user may not have all of this figured out. That's fine — help them discover it. Ask "what would break this character?" or "what choice would they dread most?" These questions often unlock depth the user hasn't articulated.

PHASE 3: CHARACTER CORE QUESTIONS
From the depth material, derive 1-3 **character core questions** — the thematic challenges this character's story should explore. These are stored as `ai:secret` in `lore.<name>`.

A character core question:
- Is a genuine question about the human condition, filtered through this specific character
- Has no clear-cut answer — the point is to challenge, not to resolve
- Emerges naturally from the character's wounds, flaws, and desires
- Will be used by `design.front` to seed fronts that resonate with this character

Examples (but they depend heavily on the specific character):
- A paladin who carries everyone's burdens: "Are you allowed to stop carrying everyone?"
- A bard who performs for love: "Can you be loved if you're not useful?"
- A gentle cleric in a brutal world: "Is staying gentle still good when gentleness stops working?"

Propose questions to the user and iterate. They should feel true to the character — the user should think "yes, that IS what this character is about." The user may not want to see the final wording (to preserve surprise during play), or they may want to refine it. Either way is fine.

PHASE 4: ASSEMBLE AND REVIEW
Produce both objects:

`pc.<name>`: lean, play-optimized. Tag with `level:N` and faction links.

`lore.<name>`: rich, planning-optimized. Include backstory, wounds, flaws, desires, red lines, misconceptions. Core questions as `ai:secret`. Do NOT tag `lore.<name>` to `pc.<name>` — it stays isolated from play context by design. Tag it only to `lore.world` or relevant factions/locations from the character's past if appropriate.

Review:
- Is `pc.<name>` under ~200 words? Could the AI voice this character distinctively from just this object?
- Does `lore.<name>` give `design.front` enough material to create fronts that challenge this character?
- Are the core questions genuinely difficult? Or are they morality checkboxes with obvious answers?
- Does `pc.<name>` accidentally contain depth that belongs in `lore.<name>`?

GUIDELINES:
- Work one PC at a time. Each character deserves a focused session.
- The user may arrive with a character sheet, a vague concept, or something in between. Meet them where they are.
- Voice is the most important thing in `pc.<name>`. If the AI can't speak AS this character distinctively, the object needs more personality details and fewer facts.
- Goals in `pc.<name>` should be actionable: not "wants peace" but "is trying to negotiate a ceasefire with the hill clans before the duke sends the army."
- The `lore.<name>` object is the user's partner in storytelling — it helps the AI challenge the character in ways that feel earned and personal. Treat it with care.
