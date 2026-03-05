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
# kb_with_tag handler — delegates to commands/kb.py, identical to CLI behaviour
# ---------------------------------------------------------------------------


async def _kb_with_tag(args: dict[str, Any], project_root: Path) -> str:
    tags: list[str] = args.get("tags") or []
    if not tags:
        return "(no tags provided)"
    recurse_raw = args.get("recurse")
    recurse: int | None = int(recurse_raw) if recurse_raw is not None else None
    expand: bool = bool(args.get("expand", False))

    result = _cmd_kb_with_tag(tags, expand=expand, recurse=recurse)
    if not result.ids:
        return f"(no KB objects found with tags: {', '.join(tags)})"

    parts: list[str] = [f"IDs: {', '.join(result.ids)}"]
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
            "entity (npc, loc, faction, front, lore, pc, spell, stat, etc.) before "
            "writing about it. Append '+' to an ID (e.g. 'npc.gandalf+') to also fetch "
            "objects linked from it. Read-only."
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
    "kb_with_tag",
    CommandToolDef(
        description=(
            "Find all KB objects that have ALL of the given tags. Useful for discovering "
            "available entities of a type or linked to a specific object "
            "(e.g. all factions, all locations in a region, all NPCs in a faction). "
            "Returns matching IDs by default; set expand=true to also return full object text. "
            "Read-only."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Tags all matched objects must have. "
                        "Examples: ['faction'], ['loc.springfield'], ['npc', 'faction.thieves-guild']"
                    ),
                },
                "expand": {
                    "type": "boolean",
                    "description": (
                        "If true, return the full text of each matched object in addition to IDs. "
                        "Default false (IDs only)."
                    ),
                },
                "recurse": {
                    "type": "integer",
                    "description": (
                        "If set, recursively follow dot-tags to this depth "
                        "(0 = unlimited). Omit for a flat tag lookup."
                    ),
                },
            },
            "required": ["tags"],
        },
    ),
    _kb_with_tag,
)
