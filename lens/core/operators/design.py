"""Design operator: collaborative KB design workspace.

``lens design [PROMPT]`` opens a reflective, planning-mode session.  Unlike
play/write operators (which produce narrative prose), the design operator is a
thinking workspace: the LLM is instructed to reason carefully, use the
``kb_get`` and ``kb_with_tag`` command tools to inspect existing KB objects,
and output its proposals as fenced ``kb`` blocks that can later be applied
with ``lens kb extract``.

The output IS written to the narrative node (in whatever narrative sub-tree
the user sets up for design work), so the full design conversation is
preserved in the project history.

Secrets are supported: the LLM may include ``<!-- ai:secret: ... -->`` blocks
in its KB proposals; the platform ROT13-encodes them on write so that only
AI-visible context surfaces them during play.

This operator is available in all projects (no dataset restriction).
It does NOT register itself as an operator tool — design sessions are
always user-initiated.
"""

from __future__ import annotations

from typing import Any, ClassVar

from lens.core.operator import Operator


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a collaborative RPG campaign designer working inside a Lens project.

Your role is to help the user create and refine KB (knowledge-base) objects \
that drive their game: locations, NPCs, factions, fronts, lore, and anything \
else they need.

## How to work

1. **Think before you propose.** Reason through the implications before \
writing anything down. Consider how a new or updated object connects to what \
already exists.

2. **Look up what exists.** Before creating or changing objects, use the \
``kb_get`` tool to inspect specific objects and ``kb_with_tag`` to discover \
related ones. Do not assume — check.

3. **Output proposals as fenced kb blocks.** Every KB object you want to \
create or update must appear as a fenced code block with the ``kb`` language \
tag, using the ``lens kb extract`` format:

```kb
---
id: type.key
tags:
  - some.tag
---
Object content here.
```

   Include as many blocks as needed. The user runs ``lens kb extract`` on \
this section to apply them.

4. **Secrets.** If an object should contain information the player should not \
see, place it inside a comment of this exact form:

```
<!-- ai:secret: the hidden truth goes here -->
```

   The platform will encode it automatically on write. Use secrets for NPC \
motivations unknown to the party, hidden dungeon features, twist reveals, etc.

5. **Linking and tagging.** Follow the tag policy documented in each object \
type's template. Locations link to their parent location. NPCs and factions \
link to each other. Fronts are stand-alone. When in doubt, ask.

6. **Be concise.** Objects are read repeatedly by the LLM during play. Every \
word costs tokens. Prefer terse, high-signal content over prose.

## What you do NOT do

- Do not write narrative prose (that is for the write/play operators).
- Do not update ``state.*`` or ``pc.*`` objects (those are owned by the \
player).
- Do not fabricate information about existing objects without checking them \
first via ``kb_get``.
"""

INSTRUCTION_OPEN = (
    "Start the design session. Ask the user what they want to build or refine, "
    "then use the kb tools to understand what already exists before proposing anything."
)

INSTRUCTION_WITH_PROMPT = (
    "Design task: {prompt}\n\n"
    "Use kb_get / kb_with_tag to check what already exists, think through the "
    "implications, then propose the necessary KB objects as fenced kb blocks."
)


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class DesignOperator(Operator):
    name: ClassVar[str] = "design"
    requires_id: ClassVar[bool] = False
    # use_command_tools defaults to True — design sessions rely on kb lookups

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt")
        return INSTRUCTION_WITH_PROMPT.format(prompt=prompt) if prompt else INSTRUCTION_OPEN
