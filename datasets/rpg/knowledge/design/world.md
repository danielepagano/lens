# [DESIGN MODULE]: WORLD AND SETTING

Establish the setting and tone for a new game. This produces `lore.world` — a concise, character-agnostic object that will be pinned to EVERY play interaction. It is the AI's primary voice and atmosphere guide.

This module is about TONE AND FRAME, not content. Deep lore, history, and geography go in separate `lore.*` objects. `lore.world` is a system-like prompt: compact, evocative, and stable.

STEP 1: CHECK FOR EXISTING SETTING
Use `kb_get` to check if a setting lore object already exists (e.g. `lore.grim-hollow`, or any `lore.*` the user mentions). If one exists, use it as the baseline — don't reinvent what the dataset already provides. Ask the user what they want to keep, change, or emphasize.

STEP 2: ESTABLISH THE FRAME
If no baseline exists, or the user wants something custom, ask about:
- Genre and tone (dark fantasy, heroic, horror, intrigue, comedic, etc.)
- Technology and magic level
- Key constraints that make this world different from generic fantasy
- Boundaries: what to avoid (tone violations, anachronisms, specific tropes)
- Emphasis: what to lean into (gritty violence, political scheming, romance, cosmic horror, etc.)

Don't try to build a world encyclopedia. You need just enough for the AI to maintain voice and atmosphere during play.

STEP 3: WRITE `lore.world`
The object must be under 500 words. It will be in the prompt of every play interaction, so every word costs tokens. Write it as a directive, not a description:
- What the AI should sound like when narrating in this world
- What the world feels like to inhabit (sensory, social, emotional)
- Hard rules the AI must follow (magic costs, technology limits, social structures)
- What makes this world distinct 

Do NOT include:
- Character-specific information (that's `pc.*` and `lore.<name>`)
- Plot or adventure hooks (that's `front.*`)
- Geography details (that's `location.*`)
- Deep history or cosmology (that's separate `lore.*` objects)

STEP 4: OPTIONAL DEEP LORE
If the setting has details worth preserving but too heavy for `lore.world`, create separate `lore.*` objects (e.g. `lore.cosmology`, `lore.history`, `lore.magic-system`). These are NOT pinned during play — they exist for design sessions to reference when building content. Tag them to `lore.world` for discoverability.

STEP 5: REVIEW
Read back the `lore.world` object and ask:
- Is it under 500 words?
- Could the AI narrate a tavern scene, a combat, and a quiet moment using only this object for tone guidance?
- Does it say anything that should live in a separate object instead?
- Does it avoid prescribing content (plot, characters, specific locations)?
