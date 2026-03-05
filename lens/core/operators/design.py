"""Design operator: collaborative KB design workspace.

``lens design <id> [PROMPT]`` opens a one-shot planning session in its own
sub-node.  The LLM reasons with extended thinking, uses ``kb_get`` and
``kb_with_tag`` to inspect existing KB objects, and outputs proposals as
fenced ``kb`` blocks (``lens kb extract`` format).  After generation, the
operator automatically applies those blocks to the knowledge store and writes
a self-closing ``[design:<id>/]: #`` annotation in the parent — the sub-node
file is preserved as a durable record of the design session.

Secrets: the LLM may include ``<!-- ai:secret: plaintext -->`` in its KB
proposals; the platform ROT13-encodes them on write.

Design is available in all projects.  It does not register as an operator
tool — sessions are always user-initiated.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

from lens.core.command_tools import get_command_registry
from lens.core.commands.kb import KbExtractResult, parse_kb_fences
from lens.core.context import crawl
from lens.core.knowledge import KnowledgeStore, parse_id
from lens.core.llm import LLMError, generate_stream
from lens.core.narrative import NarrativeNode
from lens.core.operator import Operator, OperatorError
from lens.core.project import ProjectSession, validate_slug
from lens.core.storage import Storage

logger = logging.getLogger(__name__)


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

   Include as many blocks as needed.

4. **Secrets.** If an object should contain information the player should not \
see, place it inside a comment of this exact form — write the plaintext and \
the platform encodes it automatically:

```
<!-- ai:secret: the hidden truth goes here -->
```

5. **Linking and tagging.** Follow the tag policy documented in each object \
type's template. Locations link to their parent location. NPCs and factions \
link to each other. When in doubt, ask.

6. **Be concise.** Objects are read repeatedly by the LLM during play. Every \
word costs tokens. Prefer terse, high-signal content over prose.

## What you do NOT do

- Do not write narrative prose (that is for write/play).
- Do not update ``state.*`` or ``pc.*`` objects (owned by the player).
- Do not fabricate details about existing objects without checking them first.
"""

INSTRUCTION_OPEN = (
    "Start the design session. Ask the user what they want to build or refine, "
    "then use the kb tools to understand what already exists before proposing anything."
)

INSTRUCTION_WITH_PROMPT = (
    "Design task: {prompt}\n\n"
    "Use kb_get / kb_with_tag to check what already exists, think through "
    "implications, then propose the necessary KB objects as fenced kb blocks."
)


# ---------------------------------------------------------------------------
# Operator class
# ---------------------------------------------------------------------------


class DesignOperator(Operator):
    name: ClassVar[str] = "design"
    requires_id: ClassVar[bool] = True
    use_command_tools: ClassVar[bool] = True

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_instruction(self, params: dict[str, Any]) -> str:
        prompt = params.get("prompt")
        return INSTRUCTION_WITH_PROMPT.format(prompt=prompt) if prompt else INSTRUCTION_OPEN

    # ------------------------------------------------------------------
    # KB fence application
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_kb_fences(
        content: str,
        project_root: Path,
        storage: Storage,
    ) -> KbExtractResult:
        """Parse ```kb blocks from *content* and apply them via *storage*."""
        entries, errors = parse_kb_fences(content)
        result = KbExtractResult(errors=list(errors))

        if not entries:
            return result

        kb = KnowledgeStore.for_project(project_root, storage=storage)
        for entry in entries:
            try:
                parse_id(entry.id)
            except ValueError as e:
                result.errors.append(
                    f"invalid KB id '{entry.id}': {e}"
                )
                continue
            is_new = not kb.exists(entry.id)
            kb.store_object(entry.id, entry.content)
            if entry.tags:
                err = kb.add_tags(entry.id, entry.tags)
                if err:
                    result.errors.append(f"tag error for '{entry.id}': {err}")
            (result.inserted if is_new else result.updated).append(entry.id)

        return result

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    @classmethod
    async def run_design(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        id: str,
        prompt: str | None = None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> KbExtractResult:
        """Create a design sub-node, generate content, apply kb fences, self-close.

        Returns the :class:`~lens.core.commands.kb.KbExtractResult` from
        applying the generated kb blocks (for reporting in the CLI).

        Raises :class:`~lens.core.operator.OperatorError` on user-visible
        failures.
        """
        if not validate_slug(id):
            raise OperatorError(
                f"invalid design id '{id}' — use alphanumeric characters, "
                "underscores, and hyphens only"
            )

        cursor = narrative.find_cursor()
        if id in cursor.child_keys():
            raise OperatorError(
                f"design node '{id}' already exists; "
                "use 'lens rollback' to undo or choose a different id"
            )

        rel_path = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)

        # Promote cursor to folder and create an empty child node file.
        if cursor.is_leaf():
            cursor.to_folder(storage)
        child_md = cursor.md_path().parent / f"{id}.md"
        storage.write_file(child_md, "")

        # Write self-closing annotation to parent immediately so the
        # transaction is recorded even if generation is interrupted.
        self_close_tag = op.build_self_closing_tag(id)
        op.append_to_node(cursor, self_close_tag + "\n")

        # Build prompt.
        ann_params: dict[str, Any] = {}
        if prompt:
            ann_params["prompt"] = prompt
        crawl_result = crawl(cursor, extra_pins=pins, extra_unpins=unpins)
        from lens.core.context import assemble_prompt
        messages = assemble_prompt(
            crawl_result,
            system_prompt=op.system_prompt,
            instruction=op.build_instruction(ann_params),
        )

        # Build command tool payload (kb_get, kb_with_tag).
        cmd_registry = get_command_registry()
        tools_payload = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": cmd_def.description,
                    "parameters": cmd_def.parameters,
                },
            }
            for name, (cmd_def, _) in cmd_registry.items()
        ]
        command_handlers = {name: fn for name, (_, fn) in cmd_registry.items()}

        # Generate with extended thinking + command tools.
        content = ""
        interrupted = False
        try:
            async for event in generate_stream(
                messages,
                session.project_root,
                llm_id=llm_id,
                tools=tools_payload if tools_payload else None,
                command_tool_handlers=command_handlers if command_handlers else None,
                enable_thinking=True,
            ):
                if event.preview and on_token:
                    await on_token(event.preview)
                if event.final:
                    if event.final.interrupted:
                        interrupted = True
                        break
                    content = event.final.text
                    break
        except KeyboardInterrupt:
            interrupted = True
        except LLMError as e:
            raise OperatorError(f"LLM error: {e}") from e

        if interrupted:
            # Partial content is still useful; write what we have.
            if content.strip():
                storage.write_file(child_md, content + "\n")
            return KbExtractResult()

        if not content.strip():
            raise OperatorError("no content generated")

        # Write content to the sub-node.
        storage.write_file(child_md, content + "\n")

        # Apply kb fences from the generated content using the same storage
        # transaction so narrative + KB changes commit together.
        result = cls._apply_kb_fences(content, session.project_root, storage)
        for err in result.errors:
            logger.warning("design: %s", err)

        return result
