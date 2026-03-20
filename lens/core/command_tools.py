"""Command tools: lightweight KB lookup tools callable mid-LLM-generation.

Unlike operator tools (which exit the LLM layer and hand off control),
command tools execute *inline* within the generation loop.  After the handler
returns a string result, the assistant turn + tool result are appended to the
working message list and the LLM is re-invoked without rebuilding the full
prompt.

Operators opt in by setting ``use_command_tools = True``.  Currently only
``design`` does this — operators that prioritise speed (e.g. ``play``) keep
the default of ``False``.

``kb_add`` is intentionally excluded: KB mutations belong only to planning
operators (design, advance) whose outputs go through ``lens kb extract``.
This keeps narrative writes predictable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lens.core.commands.kb import kb_get as _cmd_kb_get
from lens.core.commands.kb import kb_list_tags as _cmd_kb_list_tags
from lens.core.commands.kb import kb_with_tag as _cmd_kb_with_tag
from lens.core.knowledge import KnowledgeObject

CommandToolFn = Callable[[dict[str, Any], Path], Awaitable[str]]


@dataclass(slots=True)
class CommandToolDef:
    description: str
    parameters: dict[str, Any]  # JSON Schema for the LLM


_REGISTRY: dict[str, tuple[CommandToolDef, CommandToolFn]] = {}


def register_command_tool(
    name: str,
    tool_def: CommandToolDef,
    fn: CommandToolFn,
) -> None:
    _REGISTRY[name] = (tool_def, fn)


def get_command_registry() -> dict[str, tuple[CommandToolDef, CommandToolFn]]:
    return dict(_REGISTRY)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_objects(objects: dict[str, KnowledgeObject]) -> str:
    parts = [obj.format() for obj in objects.values()]
    return "\n\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# kb_get handler — delegates to commands/kb.py, identical to CLI behaviour
# ---------------------------------------------------------------------------


async def _kb_get(args: dict[str, Any], project_root: Path) -> str:
    ids: list[str] = args.get("ids") or []
    if not ids:
        return "(no ids provided)"
    _ordered, objects = _cmd_kb_get(ids)
    if not objects:
        return f"(no KB objects found for: {', '.join(ids)})"
    return _format_objects(objects)


# ---------------------------------------------------------------------------
# kb_list_tags handler — delegates to commands/kb.py, identical to CLI behaviour
# ---------------------------------------------------------------------------


async def _kb_list_tags(args: dict[str, Any], project_root: Path) -> str:
    type_filter: str | None = args.get("type_filter") or None
    prefix_filter: str | None = args.get("prefix_filter") or None
    tags = _cmd_kb_list_tags(type_filter=type_filter, prefix_filter=prefix_filter)
    if not tags:
        return "(no tags found)"
    return "\n".join(tags)


# ---------------------------------------------------------------------------
# kb_with_tag handler — delegates to commands/kb.py, identical to CLI behaviour
# ---------------------------------------------------------------------------


async def _kb_with_tag(args: dict[str, Any], project_root: Path) -> str:
    tags: list[str] = args.get("tags") or []
    if not tags:
        return "(no tags provided)"
    recurse_raw = args.get("recurse")
    recurse: int | None = int(recurse_raw) if recurse_raw is not None else None
    expand: bool = bool(args.get("expand", False))
    type_filter: str | None = args.get("type_filter") or None

    result = _cmd_kb_with_tag(tags, expand=expand, recurse=recurse, type_filter=type_filter)
    if not result.ids:
        return f"(no KB objects found with tags: {', '.join(tags)})"

    def _format_id_line(cid: str) -> str:
        if result.id_to_tags and cid in result.id_to_tags:
            tag_str = " ".join(result.id_to_tags[cid])
            return f"{cid}  [{tag_str}]" if tag_str else cid
        return cid

    if expand:
        parts: list[str] = []
    else:
        parts = ["IDs:\n" + "\n".join(_format_id_line(cid) for cid in result.ids)]
    if result.objects:
        formatted = _format_objects(result.objects)
        if formatted:
            parts.append(formatted)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_command_tool(
    "kb_get",
    CommandToolDef(
        description=(
            "Retrieve one or more KB objects by canonical ID. Use to look up a specific "
            "entity before writing about it. Append '+' to an ID (e.g. 'npc.gandalf+') "
            "to also fetch objects linked from it (only if needed!)"
        ),
        parameters={
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "One or more canonical KB IDs, e.g. ['npc.gandalf', 'loc.rivendell']. "
                        "Append '+' to fetch linked objects too, e.g. ['npc.gandalf+']."
                    ),
                },
            },
            "required": ["ids"],
        },
    ),
    _kb_get,
)

register_command_tool(
    "kb_list_tags",
    CommandToolDef(
        description=(
            "List unique tag values from the knowledge store. Use to discover available tags "
            "(e.g. CR values, creature types, habitats). Optionally filter by object type "
            "or tag prefix. Read-only."
        ),
        parameters={
            "type": "object",
            "properties": {
                "type_filter": {
                    "type": "string",
                    "description": (
                        "Only list tags that appear on objects of this type "
                        "(e.g. 'stat' for stat blocks, 'spell' for spells)."
                    ),
                },
                "prefix_filter": {
                    "type": "string",
                    "description": (
                        "Only list tags that start with this prefix "
                        "(e.g. 'cr:' for CR tags, 'type:' for creature types)."
                    ),
                },
            },
        },
    ),
    _kb_list_tags,
)

register_command_tool(
    "kb_with_tag",
    CommandToolDef(
        description=(
            "Find KB objects matching tag groups. AND across groups, OR within (a b c). "
            'Examples: ["type:undead", "(cr:1 cr:2)"] = undead with CR 1 or 2. '
            "Returns matching IDs, each with its full set of tags."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Tag groups. Single tags ANDed; '(a b c)' = OR within. "
                        "Examples: [\"faction\"], [\"type:undead\", \"(cr:1 cr:2 cr:3)\"]"
                    ),
                },
                "type_filter": {
                    "type": "string",
                    "description": (
                        "Only return objects of this type (e.g. 'front', 'npc', 'loc'). "
                        "Useful to narrow results when a tag is shared across many types."
                    ),
                },
            },
            "required": ["tags"],
        },
    ),
    _kb_with_tag,
)
