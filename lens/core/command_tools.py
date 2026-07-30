"""Command tools: lightweight KB lookup and media search tools callable
mid-LLM-generation.

Command tools execute *inline* within the generation loop.  After each handler
returns a string result, the assistant turn + tool results are appended to the
working message list and the LLM is re-invoked without rebuilding the full
prompt.  Multiple command tool calls in a single LLM response are all executed
before re-invoking.

Operators opt in by setting ``use_command_tools = True``.  Currently only
``design`` does this — operators that prioritise speed (e.g. ``play``) keep
the default of ``False``.

``kb_add`` is intentionally excluded: KB mutations belong only to planning
operators (design, advance) whose outputs go through ``lens kb extract``.
This keeps narrative writes predictable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from lens.core.commands.kb import kb_patch as _cmd_kb_patch
from lens.core.commands.kb import kb_with_tag as _cmd_kb_with_tag
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeObject, KnowledgeStore

CommandToolFn = Callable[[dict[str, Any], Path], Awaitable[str]]


@dataclass(slots=True)
class CommandToolDef:
    description: str
    parameters: dict[str, Any]  # JSON Schema for the LLM
    limited_to_datasets: list[str] = field(default_factory=list[str])


_REGISTRY: dict[str, tuple[CommandToolDef, CommandToolFn]] = {}


def register_command_tool(
    name: str,
    tool_def: CommandToolDef,
    fn: CommandToolFn,
) -> None:
    _REGISTRY[name] = (tool_def, fn)


def get_command_registry(
    project_root: Path | None = None,
) -> dict[str, tuple[CommandToolDef, CommandToolFn]]:
    """Return command tools, optionally filtered by the project's active datasets.

    When *project_root* is None all tools are returned (e.g. for tests that
    don't have a live project).  When provided, tools whose
    ``limited_to_datasets`` list is non-empty are excluded unless at least one
    of their required datasets is active for that project.
    """
    if project_root is not None:
        from lens.core.dataset_extensions import ensure_dataset_extensions

        ensure_dataset_extensions(project_root)
    if project_root is None:
        return dict(_REGISTRY)
    from lens.core.project import get_selected_datasets, operator_applies_to_session
    selected = get_selected_datasets(project_root)
    return {
        name: (tool_def, fn)
        for name, (tool_def, fn) in _REGISTRY.items()
        if operator_applies_to_session(selected, tool_def.limited_to_datasets)
    }


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
    kb = KnowledgeStore.for_project(project_root)
    _ordered, objects = kb.get_objects_with_links(ids)
    if not objects:
        return f"(no KB objects found for: {', '.join(ids)})"
    return _format_objects(objects)


# ---------------------------------------------------------------------------
# kb_list_tags handler — delegates to commands/kb.py, identical to CLI behaviour
# ---------------------------------------------------------------------------


async def _kb_list_tags(args: dict[str, Any], project_root: Path) -> str:
    type_filter: str | None = args.get("type_filter") or None
    prefix_filter: str | None = args.get("prefix_filter") or None
    kb = KnowledgeStore.for_project(project_root)
    tags = kb.list_unique_tags(type_filter=type_filter, prefix_filter=prefix_filter)
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

    result = _cmd_kb_with_tag(
        tags,
        expand=expand,
        recurse=recurse,
        type_filter=type_filter,
        store=KnowledgeStore.for_project(project_root),
    )
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
            "to also fetch objects linked from it (only if needed!). Do not request IDs "
            "already inlined in the user message under RELEVANT KNOWLEDGE (each object "
            "starts with a KB['id'] line)—that text is current."
        ),
        parameters={
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "One or more canonical KB IDs, e.g. ['npc.gandalf', 'location.rivendell']. "
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

# ---------------------------------------------------------------------------
# kb_patch handler — delegates to commands/kb.py, applies line-content patches.
# Intentionally *not* registered in the global tool registry: the task is to
# ship the implementation and tests only; no operator exposes it yet.
# Enable by uncommenting the ``register_command_tool('kb_patch', ...)`` call
# at the bottom of this file once an operator is ready to use it.
# ---------------------------------------------------------------------------


async def kb_patch_handler(args: dict[str, Any], project_root: Path) -> str:
    raw_id = args.get("id")
    patches = args.get("patches")
    if not raw_id or not isinstance(raw_id, str):
        return "(error: missing or invalid 'id')"
    if not isinstance(patches, list) or not patches:
        return "(error: 'patches' must be a non-empty array)"
    store = KnowledgeStore.for_project(project_root)
    patches_list: list[dict[str, Any]] = cast(list[dict[str, Any]], patches)
    try:
        result = _cmd_kb_patch(raw_id, patches_list, store=store)
    except LensException as e:
        return f"(error: {e})"
    if result.kind == "patched":
        return f"OK: patched {result.obj.id}\n\n{result.obj.format()}"
    if result.kind == "no_changes":
        return f"OK: no changes for {result.obj.id}"
    return f"OK: already present for {result.obj.id}"


KB_PATCH_TOOL = CommandToolDef(
    description=(
        "Patch a KB object's body by replacing line ranges without line numbers. "
        "Each end of a range is identified by the exact full text of one line "
        "(minus its newline), optionally plus full adjacent lines in "
        "'before'/'after' to disambiguate when the same line repeats. Each "
        "'before'/'after' entry must be a complete line, never a fragment. "
        "Sentinels '@@@start' and '@@@end' mark document boundaries. Patches "
        "apply in order and re-resolve against the current text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Canonical KB id (e.g. 'person.amy').",
            },
            "patches": {
                "type": "array",
                "description": (
                    "List of patches. Each patch replaces the selected line "
                    "range with 'content'. Use an empty content string for "
                    "deletion. Omit 'end' for a single-line target."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {
                            "type": "object",
                            "description": (
                                "Start of the selection. 'target' is the exact full line to match "
                                "(minus newline), '@@@start', or '@@@end'. Do not use a substring or "
                                "partial line as 'target'. If that line is unique, omit 'before' and "
                                "'after'. Otherwise 'before'/'after' are full adjacent lines only "
                                "(verbatim, never fragments)."
                            ),
                            "properties": {
                                "target": {"type": "string"},
                                "before": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "after": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["target"],
                        },
                        "end": {
                            "type": "object",
                            "description": (
                                "Optional end of an inclusive range. Same rules as 'start': "
                                "exact full line as 'target' (or sentinels); omit 'before'/'after' "
                                "when unique; otherwise full adjacent lines only."
                            ),
                            "properties": {
                                "target": {"type": "string"},
                                "before": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "after": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["target"],
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "Replacement text. Split into lines with "
                                "splitlines(); a trailing newline is ignored. "
                                "Empty string = pure deletion."
                            ),
                        },
                    },
                    "required": ["start", "content"],
                },
            },
        },
        "required": ["id", "patches"],
    },
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
                        "Only return objects of this type (e.g. 'front', 'npc', 'location'). "
                        "Useful to narrow results when a tag is shared across many types."
                    ),
                },
            },
            "required": ["tags"],
        },
    ),
    _kb_with_tag,
)

# ---------------------------------------------------------------------------
# media_search handler — searches the project's media mount
# ---------------------------------------------------------------------------


def _format_search_result(relative_path: str, score: int) -> str:
    return f"  [{score}] {relative_path}"


async def _media_search(args: dict[str, Any], project_root: Path) -> str:
    from lens.core.exceptions import MediaSearchCapacityExceeded
    from lens.core.media import MediaCache, MediaService, SearchPage
    from lens.core.project import get_media_search_index_limit, get_mount_backend

    query: str = (args.get("query") or "").strip()
    if not query:
        return "(error: query is required)"

    raw_page = args.get("page")
    page: int = 1
    if raw_page is not None:
        try:
            page = int(raw_page)
        except (ValueError, TypeError):
            return f"(error: invalid page number: {raw_page})"

    backend = get_mount_backend(project_root)
    if backend is None:
        return "(no media mount configured — set [project] mount_point in lens.toml)"

    limit = get_media_search_index_limit(project_root)
    svc = MediaService(backend, cache=MediaCache(search_index_limit=limit))
    try:
        result: SearchPage = svc.search(query, page=page)
    except MediaSearchCapacityExceeded as e:
        return f"(error: {e})"

    if not result.items:
        if result.total_items == 0:
            return "(no results found for query)"
        return f"(page {result.current_page} is empty — query has {result.total_items} total results across {result.total_pages} pages)"

    lines: list[str] = [
        f"Media search results (page {result.current_page}/{result.total_pages}, "
        f"{len(result.items)} of {result.total_items} total):"
    ]
    for r in result.items:
        lines.append(_format_search_result(r.relative_path, r.score))

    if result.current_page < result.total_pages:
        lines.append(
            f"\n[Use media_search with page={result.current_page + 1} to see the next page.]"
        )

    lines.append(
        "\n---\nTo refine your search: use required terms (word!) to narrow, "
        "key:value to filter by metadata (e.g. type:image), "
        "and optional terms to rank results."
    )
    return "\n".join(lines)


MEDIA_SEARCH_TOOL_DEF = CommandToolDef(
    description=(
        "Search media files on the project's mount (images, videos, audio, documents). "
        "Query syntax — space-separated tokens:\n"
        "  word!       — required term (must appear somewhere in the file path or metadata)\n"
        "  key:value   — filter by metadata key=value (e.g. type:image, character:amy)\n"
        "  path/sub:val — nested metadata filter (e.g. composite/type:subject)\n"
        "  word        — optional keyword (helps rank results; at least one must match)\n\n"
        "ALWAYS use required terms (word!) when you know what you need. "
        "Use optional keywords to disambiguate between similar results. "
        "Examples:\n"
        '  - "amy!" → find anything related to "amy"\n'
        '  - "type:image character:amy" → all images tagged with character=amy\n'
        '  - "house! bed couch" → files containing "house" (required), ranked by "bed" and "couch"\n\n'
        "Results are returned 20 per page.  Use the page parameter to navigate."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query string. Space-separated tokens: "
                    "word! for required terms, key:value for metadata filters, "
                    "word for optional ranking keywords. "
                    "Examples: 'amy!', 'type:image character:amy', 'house! bed couch'."
                ),
            },
            "page": {
                "type": "integer",
                "description": "Page number (1-indexed, default 1, max 20 results per page).",
            },
        },
        "required": ["query"],
    },
)


def build_media_search_tool_entry() -> tuple[dict[str, Any], CommandToolFn]:
    """Build a single tool-entry for media_search.

    Returns (openai_tool_dict, handler) for manual wiring into an operator's
    ``_inline_command_tools_bundle``.
    """
    tool_spec = {
        "type": "function",
        "function": {
            "name": "media_search",
            "description": MEDIA_SEARCH_TOOL_DEF.description,
            "parameters": MEDIA_SEARCH_TOOL_DEF.parameters,
        },
    }
    return tool_spec, _media_search
