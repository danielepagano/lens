"""Design operator: collaborative KB design workspace.

``lens design <id> [PROMPT]`` opens a one-shot planning session in its own
sub-node.  The LLM reasons with extended thinking, uses ``kb_get`` and
``kb_with_tag`` to inspect existing KB entries, and outputs proposals as
fenced ``kb`` blocks (``lens kb extract`` format).  After generation, the
operator automatically applies those blocks to the knowledge store.

The parent node gets an open ``[design:<id>]: #`` annotation written before
generation starts. The annotation is closed only when the user runs
``lens design end`` (cursor in the design sub-node); that command runs
``kb_extract_from_text`` on the full sub-node content and appends the
close tag to the parent (no summary text between the tags).

Continue behaviour: if a pending transaction for the same design id already
exists (open tag but no close tag), running ``lens design <id> [prompt]``
again appends a new generation round to the existing sub-node. Context
assembly uses the design sub-node as CURRENT PASSAGE so the conversation
can continue.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from lens.core.command_tools import get_command_registry
from lens.core.commands.kb import KbExtractResult, kb_extract_from_text
from lens.core.context import assemble_prompt, crawl
from lens.core.llm import LLMError, generate_stream
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operator import Operator, OperatorError
from lens.core.project import ProjectSession, validate_slug

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a collaborative story element designer. 
Your role is to help the user create and refine knowledge base (KB)) entries \
that drive a system that lets them collaborate with AI write stories or do \
role-playing and interactive fiction. These entries are things like locations, \
characters, factions,, lore, problems for the characters to solve, etc.

Each entry has a type and a key (id=type.key), and each type has a template, \
which will be provided or can fetch using an ID of type._template. \
KB entries also have TAGS, which can be used to in searches, or link them to \
each other when the tag is another entry id.

There are usually entries already filled in and provided for context, and maybe \
even an ongoing story. For example, we could have a character KB[person.alice] \
going to a place KB[loc.wonderland] already defined, and you are asked to fill \
a new KB[loc.croquet-field] that a tag of 'loc.wonderland' to link to where it is in.

In some cases, like if working in a more structured system like a role-playing game, \
you will also be provided more specific instructions, for example KB[design.encounter] \
could be used to instruct you on how to design RPG combat encounters; these instructions \
may even be paired with tools you can call with your tool-calling capabilities.

HOW TO WORK:

1. Think before you propose. Reason through the implications before \
writing anything down. Consider how a new or updated entry connects to what \
already exists. 

2. Look up what exists. Before creating or changing entries, use tools like \
``kb_get`` tool to inspect specific entries and ``kb_with_tag`` to discover \
related entries. Do not assume — check. If an entry you write has the same key \
as an existing one it will overwrite it, so you MUST preserve previous details! \
Provided RELEVANT KNOWLEDGE items are KB entries and you can assume they are \
both relevant and are fresh.

3. Output proposals as fenced kb blocks. Every KB entry you want to \
create or update must appear as a fenced code block with the ``kb`` language \
tag, using this format:

```kb
---
id: type.key
tags:
  - link.tag (dot notation links this entry to an entry with that type.key) 
  - key:value (used for standardized classification) 
  - simple
---
Entry text here (should be based on type._template). 
```

Include as many blocks as needed, and you can write any text around blocks to \
discuss or explain; only the blocks have side-effects in the knowledge base.

4. Use Temaplates. Before creating a new entry or making major changes, \
get the template: <type>._template. It will contains instructions of its purpose, \
what to include, and how to tag it. Follow this tag policy.

5. Be concise. Entries are read repeatedly by the LLM during play. Every \
word costs tokens. Prefer terse, high-signal content over prose in KB.

6. Iterate. If you emit a kb entry and the user wants changes, emit it again \
with the requested changes. Only the last instance of any entry you emit will be inserted.

What NOT to do:

- Do not write narrative prose (you are currently planning/world-building).
- Do not create or update entry types or subjects topics you were not asked to. 
- Do not fabricate details about existing entries without checking them first.
"""

INSTRUCTION_OPEN = (
    "Start the design session. Ask the user what they want to build or refine, "
    "then use the kb tools to understand what already exists before proposing anything."
)

INSTRUCTION_WITH_PROMPT = (
    "Design task: {prompt}\n\n"
    "Use kb_get / kb_with_tag to check what already exists, think through "
    "implications, ask as many questions as you'd like, then propose the "
    "necessary KB entries as fenced kb blocks."
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
        cancel_event: asyncio.Event | None = None,
    ) -> KbExtractResult:
        """Create (or continue) a design sub-node, generate content, apply kb fences.

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

        # Detect an interrupted design: the cursor may have descended into the
        # design sub-node because the open annotation was written but the close
        # tag was not yet appended.  In that case, step back to the parent.
        is_interrupted = False
        if cursor.key_path and cursor.key_path[-1] == id:
            parent = NarrativeNode(
                narrative_root=cursor.narrative_root,
                key_path=cursor.key_path[:-1],
            )
            parent_text = parent.md_path().read_text(encoding="utf-8")
            open_ann = find_unclosed_cursor_annotation(parent_text)
            if open_ann is not None and open_ann.operator == cls.name and open_ann.id == id:
                is_interrupted = True
                cursor = parent

        if not is_interrupted and id in cursor.child_keys():
            raise OperatorError(
                f"design node '{id}' already exists; "
                "use 'lens rollback' to undo or choose a different id"
            )

        rel_path = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)

        if not is_interrupted:
            # Fresh: create sub-node file and write open annotation to parent.
            if cursor.is_leaf():
                cursor.to_folder(storage)
            storage.write_file(cursor.md_path().parent / f"{id}.md", "")
            op.append_to_node(cursor, op.build_open_tag(id) + "\n")

        # Path to the child sub-node file (recomputed after possible folder promotion).
        child_md = cursor.md_path().parent / f"{id}.md"

        # Use the design child node for context so CURRENT PASSAGE is the sub-node content.
        design_child = NarrativeNode(
            narrative_root=cursor.narrative_root,
            key_path=cursor.key_path + (id,),
        )
        ann_params: dict[str, Any] = {}
        if prompt:
            ann_params["prompt"] = prompt
        crawl_result = crawl(design_child, extra_pins=pins, extra_unpins=unpins)
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
                cancel_event=cancel_event,
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
                existing = child_md.read_text(encoding="utf-8") if child_md.exists() else ""
                sep = "\n" if existing.endswith("\n") else "\n\n"
                storage.write_file(child_md, existing + sep + content + "\n")
            return KbExtractResult()

        if not content.strip():
            raise OperatorError("no content generated")

        # Append generated content to sub-node file (session stays open until design end).
        # kb_extract_from_text runs only on close (run_design_end).
        existing = child_md.read_text(encoding="utf-8") if child_md.exists() else ""
        sep = "\n" if existing.endswith("\n") else "\n\n"
        storage.write_file(child_md, existing + sep + content + "\n")

        return KbExtractResult()

    @classmethod
    async def run_design_end(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
    ) -> KbExtractResult:
        """Close the current design session: run kb_extract on sub-node content and append close tag.

        Cursor must be in the design sub-node. Appends ``[/design:<id>]: #`` to the parent
        (no content between the tags). Returns the result of kb_extract_from_text on the
        full sub-node content.
        """
        cursor = narrative.find_cursor()
        if not cursor.key_path:
            raise OperatorError("no open design to close (cursor at root)")
        id = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=cursor.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        parent_text = parent.md_path().read_text(encoding="utf-8")
        open_ann = find_unclosed_cursor_annotation(parent_text)
        if open_ann is None or open_ann.operator != cls.name or open_ann.id != id:
            raise OperatorError(
                f"parent does not have unclosed [design:{id}]: # — "
                "cursor must be in the design sub-node"
            )
        child_text = cursor.md_path().read_text(encoding="utf-8")
        rel_path = str(parent.md_path().relative_to(session.git_root))
        owner = cls.owner_id(id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)
        result = kb_extract_from_text(child_text, session.project_root, storage)
        for err in result.errors:
            logger.warning("design end: %s", err)
        op.append_to_node(parent, op.build_close_tag(id) + "\n")
        return result
