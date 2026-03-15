<!-- Design workflow: Session Zero. Pin this to guide a new game setup from scratch. -->
SESSION ZERO — NEW GAME SETUP

Guide the user through establishing a new game. This is the first design session for a campaign. Work through these phases in order, but be conversational — ask questions, propose ideas, let the user react.

PHASE 1: WORLD FRAME
Goal: produce a `lore.world` object (under 500 words).

Ask about:
- Setting source (published setting? homebrew? adaptation?)
- Genre and tone (dark fantasy, heroic, horror, intrigue, etc.)
- Technology and magic level
- Key constraints that make this world different
- What the AI should NEVER do in this world (tone violations, anachronisms, etc.)

If the user has a published setting, get the key details and compress them. Do NOT try to reproduce the whole setting — just enough for the AI to maintain voice and atmosphere during play. Deep lore goes in separate `lore.*` objects that design sessions can reference but play doesn't need pinned.

PHASE 2: STARTING GEOGRAPHY
Goal: produce 1–3 `loc.*` objects with parent links.

Ask about:
- Where does the adventure begin? (city, village, wilderness, dungeon, etc.)
- What's the immediate area like? (one level up: the region or district)
- Any specific locations that matter right away? (a tavern, a guild hall, a ruin)

Fetch `loc._template` before creating. Each location links to its parent via tag. Keep descriptions sensory and compact — what a character would notice, not encyclopedic detail.

PHASE 3: OPENING SITUATION
Goal: produce 1 `front.*` and optionally 1 `encounter.*`, plus any `npc.*` or `faction.*` needed.

Ask about:
- What's the first problem or hook? (a job, a mystery, a threat, an arrival)
- Who's involved? (patron, antagonist, bystanders)
- What's at stake if the PCs do nothing?

Create a front for the driving tension. If there's a clear opening scene (meeting a patron, arriving during a crisis, being attacked), create an encounter object for it. Create NPC objects only for characters who will recur — one-off vendors and guards don't need objects.

PHASE 4: REVIEW
Before closing, review what was created:
- List all objects produced with their IDs
- Check that links and tags are consistent
- Identify what's still missing for play to work (usually: the PC objects, which the user creates separately via `design.pc`)
- Suggest what the first `play` session might look like

DO NOT create PC objects in session zero — those are the player's domain and use `design.pc`.
DO NOT create deep lore objects unless the user specifically asks — keep it lean for now.
DO NOT create rules objects — the dataset provides those.
