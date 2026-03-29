from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from lens.core.address import NarrativeAddress
from lens.core.context import (
    assemble_prompt_kb_edit,
    crawl,
    crawl_result_from_pins,
)
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeObject, KnowledgeStore, parse_id
from lens.core.llm import LLMError, generate_stream
from lens.core.project import find_git_root_from, find_project_root, is_dataset_root, resolve_address
from lens.core.storage import Storage


def get_store() -> KnowledgeStore:
    try:
        root = find_project_root()
    except RuntimeError as e:
        raise LensException(str(e)) from e
    return KnowledgeStore.for_project(root)

def kb_add(id: str, content: str | None, use_template: bool) -> None:
    try:
        parse_id(id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = get_store()
    kb.store_object(id, content, use_template=use_template)

def kb_template(
    type_name: str,
    content: str | None,
    *,
    store: KnowledgeStore | None = None,
) -> str | None:
    kb = store if store is not None else get_store()
    if content is not None:
        kb.set_template(type_name, content)
        return None
    return kb.get_template(type_name)

def kb_tag(
    id: str,
    add: list[str],
    remove: list[str],
    *,
    store: KnowledgeStore | None = None,
) -> tuple[list[str], list[str]]:
    try:
        parse_id(id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = store if store is not None else get_store()
    if add:
        err = kb.add_tags(id, add)
        if err is not None:
            raise LensException(err)
    if remove:
        kb.remove_tags(id, remove)
    current = kb.get_tags(id)
    invalid = kb.get_invalid_dot_tags(current) if current else []
    return current, invalid

def kb_delete(id: str, *, store: KnowledgeStore | None = None) -> None:
    try:
        parse_id(id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = store if store is not None else get_store()
    kb.delete_object(id)


def kb_copy(
    source_id: str,
    target_id: str,
    *,
    store: KnowledgeStore | None = None,
) -> None:
    try:
        parse_id(source_id)
        parse_id(target_id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = store if store is not None else get_store()
    try:
        kb.copy_object(source_id, target_id)
    except ValueError as e:
        raise LensException(str(e)) from e


def kb_rename(
    old_id: str,
    new_id: str,
    *,
    store: KnowledgeStore | None = None,
) -> None:
    try:
        parse_id(old_id)
        parse_id(new_id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = store if store is not None else get_store()
    try:
        kb.rename_object(old_id, new_id)
    except ValueError as e:
        raise LensException(str(e)) from e

def kb_get(ids: list[str]) -> tuple[list[str], dict[str, KnowledgeObject]]:
    kb = get_store()
    return kb.get_objects_with_links(ids)


@dataclass
class WithTagResult:
    ids: list[str]
    layers: list[tuple[str, list[str]]] | None = None
    objects: dict[str, KnowledgeObject] | None = None
    id_to_tags: dict[str, list[str]] | None = None


def parse_tag_groups(tags: list[str]) -> list[list[str]]:
    """Parse tags into groups. (a b c) is OR within; other elements are AND across."""
    groups: list[list[str]] = []
    for t in tags:
        s = t.strip()
        if not s:
            continue
        if s.startswith("(") and s.endswith(")"):
            inner = s[1:-1].strip()
            group = [x.strip() for x in inner.split() if x.strip()]
            if group:
                groups.append(group)
        else:
            groups.append([s])
    return groups


def _filter_ids_by_tag_type(ids: list[str], tag: str) -> list[str]:
    if "." not in tag:
        return ids
    try:
        want_type, _ = parse_id(tag)
    except ValueError:
        return ids
    out: list[str] = []
    for oid in ids:
        if "." not in oid:
            continue
        try:
            t, _ = parse_id(oid)
        except ValueError:
            continue
        if t == want_type:
            out.append(oid)
    return out


def kb_with_tag(
    tags: list[str],
    *,
    expand: bool = False,
    recurse: int | None = None,
    same_type_only: bool = False,
    type_filter: str | None = None,
    store: KnowledgeStore | None = None,
) -> WithTagResult:
    if not tags:
        raise LensException("at least one tag is required")
    groups = parse_tag_groups(tags)
    if not groups:
        raise LensException("at least one tag is required")
    kb = store if store is not None else get_store()
    first_tag = groups[0][0] if groups and groups[0] else ""

    def _apply_type_filter(id_list: list[str]) -> list[str]:
        if not type_filter:
            return id_list
        prefix = f"{type_filter}."
        return [i for i in id_list if i.startswith(prefix)]

    if recurse is None:
        ids = _apply_type_filter(kb.get_ids_with_tag_groups(groups))
        if same_type_only and first_tag:
            ids = _filter_ids_by_tag_type(ids, first_tag)
        id_to_tags = {oid: kb.get_tags(oid) for oid in ids}
        if not expand:
            return WithTagResult(ids=ids, id_to_tags=id_to_tags)
        objects = kb.get_objects(ids)
        return WithTagResult(ids=ids, objects=objects, id_to_tags=id_to_tags)

    max_depth: int | None = None
    if recurse > 0:
        max_depth = recurse

    has_or_group = any(len(g) > 1 for g in groups)
    if has_or_group:
        root_ids = _apply_type_filter(kb.get_ids_with_tag_groups(groups))
        if same_type_only and first_tag:
            root_ids = _filter_ids_by_tag_type(root_ids, first_tag)
        root_ids, layers = kb.traverse_from_ids(
            root_ids,
            same_type_only=same_type_only,
            max_depth=max_depth,
            starting_type=parse_id(first_tag)[0] if "." in first_tag else None,
        )
    else:
        flat_tags = [g[0] for g in groups]
        root_ids, layers = kb.traverse_by_dot_tags(
            flat_tags,
            same_type_only=same_type_only,
            max_depth=max_depth,
        )
        root_ids = _apply_type_filter(root_ids)

    seen: set[str] = set()
    all_ids: list[str] = list(root_ids)
    for _, child_ids in layers:
        for cid in child_ids:
            if cid not in seen:
                seen.add(cid)
                all_ids.append(cid)
    id_to_tags = {oid: kb.get_tags(oid) for oid in all_ids}
    if not expand:
        return WithTagResult(ids=root_ids, layers=layers, id_to_tags=id_to_tags)
    objects = kb.get_objects(all_ids)
    return WithTagResult(ids=root_ids, layers=layers, objects=objects, id_to_tags=id_to_tags)


def kb_list_tags(
    type_filter: str | None = None,
    prefix_filter: str | None = None,
) -> list[str]:
    kb = get_store()
    return kb.list_unique_tags(
        type_filter=type_filter,
        prefix_filter=prefix_filter,
    )


def check_invalid_tags(tags: list[str]) -> list[str]:
    kb = get_store()
    return kb.get_invalid_dot_tags(tags)


def kb_edit(
    id: str,
    instruction: str,
    *,
    context_address: str | None = None,
    pins: list[str] | None = None,
    unpins: list[str] | None = None,
    include_template: bool = False,
    llm_id: str | None = None,
    on_token: Callable[[str], None] | None = None,
) -> None:
    if not instruction or not instruction.strip():
        raise LensException("instruction is required (AI instructions for what to write/change)")

    try:
        type_name, key = parse_id(id)
    except ValueError as e:
        raise LensException(str(e)) from e
    if key == "_template":
        raise LensException("kb edit targets object ids, not templates; use 'lens kb template'")

    project_root = find_project_root()
    if is_dataset_root(project_root) and context_address is not None:
        raise LensException("--context is not available in dataset mode")

    kb_store = KnowledgeStore.for_project(project_root)
    pins_list = pins or []
    unpins_list = unpins or []

    if context_address is not None:
        addr = NarrativeAddress.parse(context_address)
        resolved = resolve_address(addr, project_root)
        node = resolved.to_node(project_root)
        if not node.exists():
            raise LensException(f"context node does not exist: {context_address}")
        crawl_result = crawl(node, extra_pins=pins_list, extra_unpins=unpins_list)
    else:
        crawl_result = crawl_result_from_pins(project_root, pins_list, unpins_list)

    objs = kb_store.get_objects([id])
    existing_obj = objs.get(id)
    existing_content = existing_obj.text if existing_obj else None

    template_content: str | None = None
    if include_template or existing_content is None:
        template_content = kb_store.get_template(type_name)

    messages = assemble_prompt_kb_edit(
        crawl_result,
        instruction,
        existing_content=existing_content,
        template_content=template_content,
        include_template=include_template,
    )

    async def _run() -> str:
        full_text = ""
        try:
            async for event in generate_stream(
                messages,
                project_root,
                llm_id=llm_id,
            ):
                if event.preview and on_token:
                    on_token(event.preview)
                if event.final:
                    if event.final.interrupted:
                        return ""
                    full_text = event.final.text
                    break
        except LLMError as e:
            raise LensException(str(e)) from e
        return full_text

    content = asyncio.run(_run())
    if not content.strip():
        return

    kb_store.store_object(id, content)


# ---------------------------------------------------------------------------
# Structured KB extraction
# ---------------------------------------------------------------------------

_FENCE_OPEN_RE = re.compile(r"^```kb\s*$")
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")


@dataclass
class KbExtractEntry:
    id: str
    tags: list[str] = field(default_factory=lambda: cast(list[str], []))
    remove_tags: list[str] = field(default_factory=lambda: cast(list[str], []))
    content: str = ""
    source_line: int = 0  # 1-based line of the opening fence


@dataclass
class KbExtractResult:
    inserted: list[str] = field(default_factory=lambda: cast(list[str], []))
    updated: list[str] = field(default_factory=lambda: cast(list[str], []))
    errors: list[str] = field(default_factory=lambda: cast(list[str], []))


def parse_kb_fences(text: str) -> tuple[list[KbExtractEntry], list[str]]:
    """Parse ```kb ... ``` blocks from *text*.

    Returns ``(entries, errors)`` where errors are human-readable messages for
    blocks that could not be parsed (missing front matter, missing id, etc.).
    Empty or whitespace-only body is preserved in ``KbExtractEntry.content``;
    :func:`kb_extract_from_text` uses that to apply tag-only updates for objects
    that already exist.
    """
    entries_by_id: dict[str, KbExtractEntry] = {}
    errors: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not _FENCE_OPEN_RE.match(lines[i]):
            i += 1
            continue
        open_line = i + 1  # 1-based
        i += 1
        block: list[str] = []
        while i < len(lines) and not _FENCE_CLOSE_RE.match(lines[i]):
            block.append(lines[i])
            i += 1
        i += 1  # skip closing fence (or advance past EOF)

        # Locate the two '---' delimiters for front matter.
        dash_indices: list[int] = [
            j for j, ln in enumerate(block) if ln.strip() == "---"
        ]
        if len(dash_indices) < 2:
            errors.append(
                f"line {open_line}: kb block has no valid front matter (need two '---' lines)"
            )
            continue

        fm_start = dash_indices[0] + 1
        fm_end = dash_indices[1]
        fm_text = "\n".join(block[fm_start:fm_end])
        content_lines = block[fm_end + 1 :]
        # Strip a single leading blank line from content (common after closing ---)
        if content_lines and content_lines[0].strip() == "":
            content_lines = content_lines[1:]

        try:
            fm_raw: Any = yaml.safe_load(fm_text)
        except yaml.YAMLError as exc:
            errors.append(f"line {open_line}: YAML parse error in front matter: {exc}")
            continue

        if not isinstance(fm_raw, dict):
            errors.append(f"line {open_line}: front matter must be a YAML mapping")
            continue

        fm = cast(dict[str, Any], fm_raw)
        raw_id = fm.get("id")
        if not raw_id or not isinstance(raw_id, str):
            errors.append(f"line {open_line}: kb block is missing required 'id' field")
            continue

        raw_tags = fm.get("tags", [])
        tags: list[str] = (
            [str(t) for t in cast(list[Any], raw_tags)]
            if isinstance(raw_tags, list)
            else []
        )

        raw_remove_tags = fm.get("remove-tags", [])
        remove_tags: list[str] = (
            [str(t) for t in cast(list[Any], raw_remove_tags)]
            if isinstance(raw_remove_tags, list)
            else []
        )

        entry = KbExtractEntry(
            id=raw_id.strip(),
            tags=tags,
            remove_tags=remove_tags,
            content="\n".join(content_lines),
            source_line=open_line,
        )
        # Later blocks for the same id overwrite earlier ones entirely
        entries_by_id[entry.id] = entry

    return list(entries_by_id.values()), errors


def kb_extract_from_text(
    text: str,
    project_root: Path,
    storage: Storage,
) -> KbExtractResult:
    """Parse ``kb`` fenced blocks from *text* and upsert them into the KB store.

    Uses the provided *storage* instance so the writes join an existing
    transaction.  This is the core extraction logic shared by ``kb_extract``
    (CLI/file-path version) and the ``design`` operator (in-memory version).

    When a block's body is empty or whitespace-only after parsing, and the
    object already exists, the body is not written: only ``tags`` /
    ``remove-tags`` are applied. New objects still get an empty body (or use
    the same rules as ``store_object``) so tag-only blocks can create stubs.
    """
    entries, parse_errors = parse_kb_fences(text)
    result = KbExtractResult(errors=list(parse_errors))

    if not entries:
        return result

    kb = KnowledgeStore.for_project(project_root, storage=storage)
    for entry in entries:
        try:
            parse_id(entry.id)
        except ValueError as e:
            result.errors.append(
                f"line {entry.source_line}: invalid id '{entry.id}': {e}"
            )
            continue

        is_new = not kb.exists(entry.id)
        tags_only = not entry.content.strip()
        if not tags_only or is_new:
            kb.store_object(entry.id, entry.content)

        if entry.tags:
            err = kb.add_tags(entry.id, entry.tags)
            if err:
                result.errors.append(f"line {entry.source_line}: {err}")

        if entry.remove_tags:
            kb.remove_tags(entry.id, entry.remove_tags)

        (result.inserted if is_new else result.updated).append(entry.id)

    return result


def kb_extract(file_paths: list[str]) -> KbExtractResult:
    """Parse *file_paths* for ```kb blocks and upsert them into the KB store.

    All writes go through the KnowledgeStore singleton, which uses a single
    lazily-created Storage — so all changes land as one pending git transaction.
    """
    if not file_paths:
        return KbExtractResult()

    texts: list[str] = []
    for file_path in file_paths:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise LensException(f"file not found: {file_path}")
        texts.append(path.read_text(encoding="utf-8"))

    combined_text = "\n".join(texts)
    root = find_project_root()
    git_root = find_git_root_from(root)
    storage = Storage(git_root)
    return kb_extract_from_text(combined_text, root, storage)
