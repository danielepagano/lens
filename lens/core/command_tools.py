"""Command tools: lightweight KB lookup tools callable mid-LLM-generation.

Unlike operator tools (which exit the LLM layer and hand off control),
command tools execute *inline* within the generation loop.  After the handler
returns a string result, the assistant turn + tool result are appended to the
working message list and the LLM is re-invoked without rebuilding the full
prompt.

Currently supported:
  - ``kb_get``      — retrieve one or more KB objects by ID
  - ``kb_with_tag`` — find KB objects with all given tags

``kb_add`` is intentionally excluded: narrative writes should be predictable,
and KB mutations belong only to planning operators (design, advance, …) whose
outputs are extracted via ``lens kb extract``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lens.core.knowledge import KnowledgeObject, KnowledgeStore

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
    parts = [obj.format(include_comments=True) for obj in objects.values()]
    return "\n\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# kb_get handler
# ---------------------------------------------------------------------------


async def _kb_get(args: dict[str, Any], project_root: Path) -> str:
    ids: list[str] = args.get("ids") or []
    if not ids:
        return "(no ids provided)"
    kb = KnowledgeStore.for_project(project_root)
    _ordered, objects = kb.get_objects_with_links(ids)
    if not objects:
        return f"(no KB objects found for: {', '.join(ids)})"
    return _format_objects(objects)


# ---------------------------------------------------------------------------
# kb_with_tag handler
# ---------------------------------------------------------------------------


async def _kb_with_tag(args: dict[str, Any], project_root: Path) -> str:
    tags: list[str] = args.get("tags") or []
    if not tags:
        return "(no tags provided)"
    recurse_raw = args.get("recurse")
    recurse: int | None = int(recurse_raw) if recurse_raw is not None else None

    kb = KnowledgeStore.for_project(project_root)

    if recurse is None:
        ids = kb.get_ids_with_all_tags(tags)
        objects = kb.get_objects(ids) if ids else {}
    else:
        max_depth: int | None = recurse if recurse > 0 else None
        root_ids, layers = kb.traverse_by_dot_tags(
            tags, same_type_only=False, max_depth=max_depth
        )
        seen: set[str] = set()
        ids = list(root_ids)
        for _, child_ids in layers:
            for cid in child_ids:
                if cid not in seen:
                    seen.add(cid)
                    ids.append(cid)
        objects = kb.get_objects(ids) if ids else {}

    if not ids:
        return f"(no KB objects found with tags: {', '.join(tags)})"

    parts: list[str] = [f"IDs: {', '.join(ids)}"]
    formatted = _format_objects(objects)
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
            "writing about it. Automatically includes linked objects. Read-only."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "One or more canonical KB IDs, e.g. ['npc.gandalf', 'loc.rivendell']"
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
            "Returns IDs and full object text. Read-only."
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
