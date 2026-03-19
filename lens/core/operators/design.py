"""Design operator: collaborative KB design workspace.

``lens design [PROMPT]`` opens a design session in its own sub-node the first
time it is called, or continues the current session if the cursor is already
inside one.

Session lifecycle
-----------------
*  First call → creates a sub-node with an auto-generated id
   (``design[-module][-prompt-slug]``), writes front matter with pins/unpins,
   and appends the first inline ``[design…]: # … [/design]: #`` block.
*  Subsequent calls inside the same session → append new inline blocks to the
   existing sub-node.  Front matter is updated when ``--module`` changes or
   new pins/unpins are supplied.
*  ``--end`` → runs ``kb_extract_from_text`` on the full sub-node content and
   writes the close tag ``[/design:<id>]: #`` to the parent.

Module handling
---------------
``--module <key>`` pins ``design.<key>`` in the sub-node front matter.  The
LLM sees the module as RELEVANT KNOWLEDGE and is instructed (via the system
prompt) to treat it as a directive.  Only one module is active at a time:
switching ``--module`` removes all ``design.*`` pins before adding the new one.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from lens.core.annotations import ParsedAnnotation, parse_front_matter
from lens.core.command_tools import get_command_registry
from lens.core.commands.kb import KbExtractResult, kb_extract_from_text
from lens.core.context import assemble_prompt, crawl
from lens.core.llm import LLMError, generate_stream
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operator import Operator, OperatorError
from lens.core.pinning import pin as pin_node
from lens.core.pinning import remove_pin
from lens.core.pinning import unpin as unpin_node
from lens.core.project import ProjectSession
from lens.core.storage import Storage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a collaborative story element designer.
Your role is to help the user create and refine knowledge base (KB) entries \
that drive a system that lets them collaborate with AI write stories or do \
role-playing and interactive fiction. These entries are things like locations, \
characters, factions, lore, problems for the characters to solve, etc.

Each entry has a type and a key (id=type.key), and each type has a template, \
which will be provided or can fetch using an ID of type._template. \
KB entries also have TAGS, which can be used to in searches, or link them to \
each other when the tag is another entry id.

There are usually entries already filled in and provided for context, and maybe \
even an ongoing story. For example, we could have a character KB[person.alice] \
going to a place KB[loc.wonderland] already defined, and you are asked to fill \
a new KB[loc.croquet-field] with a tag of 'loc.wonderland' to link to where it is in.

If a DESIGN MODULE entry appears in RELEVANT KNOWLEDGE, treat its instructions \
as system-prompt priority: follow them precisely and use any tools they describe.

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
  - key:value (used for standardized classification, only if requested by template)
---
Entry text here (should be based on type._template).
```

Include as many blocks as needed, and you can write any text around blocks to \
discuss or explain; only the blocks have side-effects in the knowledge base.

4. Use Templates. Before creating a new entry or making major changes, \
get the template: <type>._template. It will contains instructions of its purpose, \
what to include, and how to tag it. Follow this tag policy. Do not over-tag.

5. Be concise. Entries are read repeatedly by the LLM during play. Every \
word costs tokens. Prefer terse, high-signal content over prose in KB.

6. Iterate. If you emit a kb entry and the user wants changes, emit it again \
with the requested changes. Only the last instance of any entry you emit will be inserted.

What NOT to do:

- Do not write narrative prose (you are currently planning/world-building).
- Do not create or update entry types or subjects topics you were not asked to.
- Do not fabricate details about existing entries without checking them first. Anything you emit overwrites anything with that id!
"""

INSTRUCTION = (
    "Design task: {prompt}\n\n"
    "Use kb_get / kb_with_tag to check what already exists, think through "
    "implications, ask as many questions as you'd like, then propose the "
    "necessary KB entries as fenced kb blocks."
)

DESIGN_MODULE_PREFIX = "design."

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_NONSLUG_RE = re.compile(r"[^a-z0-9]+")


def prompt_to_slug(prompt: str, max_words: int = 5) -> str:
    """Convert prompt text to a hyphen-joined slug of up to *max_words* words."""
    words = _NONSLUG_RE.sub(" ", prompt.lower()).split()
    return "-".join(words[:max_words])


def generate_design_id(
    prompt: str | None,
    module_id: str | None,
    parent: NarrativeNode,
) -> str:
    """Auto-generate a unique design sub-node id.

    Pattern: ``design[-module_id][-prompt_slug]`` with a numeric suffix when
    a sub-node with that name already exists.
    """
    parts = ["design"]
    if module_id:
        parts.append(module_id.strip())
    if prompt:
        slug = prompt_to_slug(prompt)
        if slug:
            parts.append(slug)
    base = "-".join(parts)
    existing = set(parent.child_keys())
    if base not in existing:
        return base
    n = 1
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def _find_active_design(
    narrative: NarrativeNode,
) -> tuple[NarrativeNode | None, str | None]:
    """Return (design_sub_node, design_id) if cursor is inside a design session.

    The cursor is *inside* a design session when ``find_cursor()`` returns a
    node whose parent has an unclosed ``[design:<id>]: #`` annotation.
    """
    cursor = narrative.find_cursor()
    if not cursor.key_path:
        return None, None
    parent = NarrativeNode(
        narrative_root=cursor.narrative_root,
        key_path=cursor.key_path[:-1],
    )
    try:
        parent_text = parent.md_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    open_ann = find_unclosed_cursor_annotation(parent_text)
    if open_ann is not None and open_ann.operator == DesignOperator.name:
        return cursor, open_ann.id
    return None, None


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
        prompt = params.get("prompt") or "Follow the design module in RELEVANT KNOWLEDGE"
        return INSTRUCTION.format(prompt=prompt)

    # ------------------------------------------------------------------
    # Front-matter helpers
    # ------------------------------------------------------------------

    @classmethod
    def _update_front_matter_for_call(
        cls,
        design_node: NarrativeNode,
        module_id: str | None,
        pins: list[str],
        unpins: list[str],
        storage: Storage,
        session: ProjectSession,
    ) -> None:
        """Update the design sub-node front matter for a subsequent call.

        - If *module_id* is provided, remove all existing ``design.*`` pins
          and add the new module pin (one module at a time).
        - Merge any new *pins* / *unpins*.
        """
        if module_id:
            fm = parse_front_matter(design_node.md_path().read_text(encoding="utf-8"))
            kb_pins: list[str] = [str(p) for p in (fm.get("kb_pin") or [])]  # type: ignore[union-attr]
            old_design_pins: list[str] = [p for p in kb_pins if p.startswith(DESIGN_MODULE_PREFIX)]
            if old_design_pins:
                remove_pin(design_node, old_design_pins, storage)
            new_module_kb_id = DESIGN_MODULE_PREFIX + module_id
            if not session.kb.exists(new_module_kb_id):
                raise OperatorError(f"design module does not exist: {new_module_kb_id}")
            pin_node(design_node, [new_module_kb_id], storage)
        if pins:
            pin_node(design_node, pins, storage)
        if unpins:
            unpin_node(design_node, unpins, storage)

    # ------------------------------------------------------------------
    # Core generation helper
    # ------------------------------------------------------------------

    @classmethod
    async def _run_generation(
        cls,
        *,
        op: "DesignOperator",
        storage: Storage,
        design_child: NarrativeNode,
        ann_params: dict[str, Any],
        existing_ann: ParsedAnnotation | None,
        session: ProjectSession,
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
    ) -> None:
        """Crawl *design_child*, generate with command tools, write to child.

        If *existing_ann* is None, writes a fresh inline block (open + content
        + close).  If *existing_ann* is provided (retry path), calls
        ``write_append`` instead.
        """
        crawl_result = crawl(design_child)
        instruction = op.build_instruction(ann_params)
        messages = assemble_prompt(
            crawl_result,
            system_prompt=op.system_prompt,
            instruction=instruction,
        )

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
            if content.strip():
                if existing_ann is not None:
                    op.write_append(design_child, existing_ann, content)
                else:
                    cls._write_inline_block(storage, design_child, ann_params, content, op)
            return

        if not content.strip():
            raise OperatorError("no content generated")

        if existing_ann is not None:
            op.write_append(design_child, existing_ann, content)
        else:
            cls._write_inline_block(storage, design_child, ann_params, content, op)

    @staticmethod
    def _write_inline_block(
        storage: Storage,
        design_child: NarrativeNode,
        ann_params: dict[str, Any],
        content: str,
        op: "DesignOperator",
    ) -> None:
        inline_tag = op.build_open_tag(None, ann_params)
        close_tag = op.build_close_tag(None)
        child_md = design_child.md_path()
        existing = child_md.read_text(encoding="utf-8") if child_md.exists() else ""
        sep = "\n" if existing.endswith("\n") else "\n\n"
        storage.write_file(
            child_md,
            existing + sep + inline_tag + "\n\n" + content.rstrip() + "\n\n" + close_tag + "\n",
        )

    # ------------------------------------------------------------------
    # Fresh design session
    # ------------------------------------------------------------------

    @classmethod
    async def _run_fresh_design(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str | None,
        module_id: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        on_token: Callable[[str], Awaitable[None]] | None,
        on_stream_target: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
    ) -> None:
        cursor = narrative.find_cursor()
        design_id = generate_design_id(prompt, module_id, cursor)

        rel_path = str(cursor.md_path().relative_to(session.git_root))
        owner = cls.owner_id(design_id, rel_path)
        storage = session.new_storage(owner=owner)
        op = cls(storage, narrative)

        # create_subnode promotes parent to folder if needed, writes empty child,
        # and appends open tag to parent.
        child_node = op.create_subnode(cursor, design_id)

        # Write initial front matter.
        all_pins = list(pins)
        if module_id:
            module_kb_id = DESIGN_MODULE_PREFIX + module_id
            if not session.kb.exists(module_kb_id):
                raise OperatorError(f"design module does not exist: {module_kb_id}")
            all_pins.append(module_kb_id)
        if all_pins:
            pin_node(child_node, all_pins, storage)
        if unpins:
            unpin_node(child_node, unpins, storage)

        # Stage the sub-node setup (creation + front matter) so that the
        # subsequent inline write gets its own storage owner based on the
        # annotation line number — this is required for --retry to work.
        storage.stage_all()

        if on_stream_target is not None:
            await on_stream_target(str(child_node.to_address()))

        ann_params: dict[str, Any] = {"steps": 1}
        if prompt:
            ann_params["prompt"] = prompt

        # Create a new storage whose owner is keyed to the inline annotation.
        child_rel_path = str(child_node.md_path().relative_to(session.git_root))
        ann_line = cls.ann_line_for_append(child_node.md_path().read_text(encoding="utf-8"))
        inline_owner = cls.owner_id(None, child_rel_path, line=ann_line)
        inline_storage = session.new_storage(owner=inline_owner)
        inline_op = cls(inline_storage, narrative)

        await cls._run_generation(
            op=inline_op,
            storage=inline_storage,
            design_child=child_node,
            ann_params=ann_params,
            existing_ann=None,
            session=session,
            llm_id=llm_id,
            on_token=on_token,
            cancel_event=cancel_event,
        )

    # ------------------------------------------------------------------
    # Continue / retry inside existing design session
    # ------------------------------------------------------------------

    @classmethod
    async def _run_inside_design(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        design_node: NarrativeNode,
        prompt: str | None,
        module_id: str | None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None,
        retry: bool,
        on_token: Callable[[str], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None,
    ) -> None:
        probe_storage = session.new_storage()

        if retry:
            # Locate the last inline annotation and verify ownership.
            has_pending = probe_storage.has_pending()
            pending_owner = probe_storage.detect_pending_owner() if has_pending else None

            probe_op = cls(probe_storage, narrative)
            existing_ann = probe_op.find_open_annotation(design_node)
            if existing_ann is None:
                raise OperatorError("no design annotation found to retry")

            child_rel_path = str(design_node.md_path().relative_to(session.git_root))
            ann_owner = cls._owner_for_ann(existing_ann, child_rel_path)
            is_owner = (pending_owner == ann_owner) if has_pending else False
            if not is_owner:
                raise OperatorError("no pending design transaction to retry")

            storage = session.new_storage(owner=ann_owner)
            op = cls(storage, narrative)

            new_params: dict[str, Any] = dict(existing_ann.params)
            if prompt:
                new_params["prompt"] = prompt

            # Update front matter before discard so context reflects new module.
            if module_id or pins or unpins:
                cls._update_front_matter_for_call(
                    design_node, module_id, pins, unpins, storage, session
                )

            op.write_discard(design_node, existing_ann, updated_params=new_params)

            fresh_ann = op.find_open_annotation(design_node)
            if fresh_ann is None:
                raise OperatorError("lost annotation after discard")

            await cls._run_generation(
                op=op,
                storage=storage,
                design_child=design_node,
                ann_params=new_params,
                existing_ann=fresh_ann,
                session=session,
                llm_id=llm_id,
                on_token=on_token,
                cancel_event=cancel_event,
            )
        else:
            # Auto-stage any pending transaction before a fresh inline block.
            if probe_storage.has_pending():
                probe_storage.stage_all()

            # Apply front-matter changes with a system-level storage, then
            # stage them so the generation starts from a clean state.
            if module_id or pins or unpins:
                fm_storage = session.new_storage()
                cls._update_front_matter_for_call(
                    design_node, module_id, pins, unpins, fm_storage, session
                )
                fm_storage.stage_all()

            ann_params: dict[str, Any] = {"steps": 1}
            if prompt:
                ann_params["prompt"] = prompt

            child_rel_path = str(design_node.md_path().relative_to(session.git_root))
            ann_line = cls.ann_line_for_append(design_node.md_path().read_text(encoding="utf-8"))
            owner = cls.owner_id(None, child_rel_path, line=ann_line)
            storage = session.new_storage(owner=owner)
            op = cls(storage, narrative)

            await cls._run_generation(
                op=op,
                storage=storage,
                design_child=design_node,
                ann_params=ann_params,
                existing_ann=None,
                session=session,
                llm_id=llm_id,
                on_token=on_token,
                cancel_event=cancel_event,
            )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    @classmethod
    async def run_design(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
        prompt: str | None = None,
        module_id: str | None = None,
        pins: list[str],
        unpins: list[str],
        llm_id: str | None = None,
        retry: bool = False,
        end: bool = False,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_stream_target: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> KbExtractResult:
        """Run a design session (create, continue, or end).

        Returns :class:`~lens.core.commands.kb.KbExtractResult` (empty unless
        ``end=True``).
        """
        if end:
            return await cls.run_design_end(session=session, narrative=narrative)

        design_node, _ = _find_active_design(narrative)

        if design_node is not None:
            await cls._run_inside_design(
                session=session,
                narrative=narrative,
                design_node=design_node,
                prompt=prompt,
                module_id=module_id,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                retry=retry,
                on_token=on_token,
                cancel_event=cancel_event,
            )
        else:
            await cls._run_fresh_design(
                session=session,
                narrative=narrative,
                prompt=prompt,
                module_id=module_id,
                pins=pins,
                unpins=unpins,
                llm_id=llm_id,
                on_token=on_token,
                on_stream_target=on_stream_target,
                cancel_event=cancel_event,
            )

        return KbExtractResult()

    # ------------------------------------------------------------------
    # End session
    # ------------------------------------------------------------------

    @classmethod
    async def run_design_end(
        cls,
        *,
        session: ProjectSession,
        narrative: NarrativeNode,
    ) -> KbExtractResult:
        """Close the current design session.

        Cursor must be in the design sub-node.  Runs ``kb_extract_from_text``
        on the full sub-node content and appends ``[/design:<id>]: #`` to the
        parent.
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
        if storage.has_pending() and storage.detect_pending_owner() == owner:
            storage.stage_all()
        op = cls(storage, narrative)
        result = kb_extract_from_text(child_text, session.project_root, storage)
        for err in result.errors:
            logger.warning("design end: %s", err)
        op.append_to_node(parent, op.build_close_tag(id) + "\n")
        return result
