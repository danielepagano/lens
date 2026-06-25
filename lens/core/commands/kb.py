from __future__ import annotations

from asyncio import Event
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from lens.core.text_select import Patch

import yaml

from lens.core.address import NarrativeAddress
from lens.core.annotations import parse_annotations, strip_markdown_comments
from lens.core.context import (
    CrawlSpec,
    assemble_prompt_kb_edit,
    crawl,
    crawl_result_from_pins,
)
from lens.core.crawl_graph import CrawlComponent, ComponentSource
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeObject, KnowledgeStore, parse_id
from lens.core.llm import build_command_tools_bundle
from lens.core.llm_run import LlmRunRequest, run_llm
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

@dataclass(frozen=True)
class KbPatchResult:
    obj: KnowledgeObject
    kind: Literal["patched", "no_changes", "already_present"]


def kb_patch(
    id: str,
    patches: list[Patch] | list[dict[str, Any]] | None,
    *,
    store: KnowledgeStore | None = None,
) -> KbPatchResult:
    """Apply a list of line-content patches to a KB object's body.

    ``patches`` may be either a list of :class:`lens.core.text_select.Patch`
    objects or a list of dicts in the tool-call shape (``{"start": ...,
    "end": ..., "content": "..."}``).  Patches are applied in order and
    each re-resolves against the current (already-patched) text.

    Raises :class:`LensException` on id/validation errors, if the object
    does not exist, or if any patch fails to resolve.  On success returns
    the updated :class:`KnowledgeObject` and an outcome kind.
    """
    # Lazy import keeps kb.py free of a hard dependency on text_select at module load.
    from lens.core.text_select import Patch as _Patch
    from lens.core.text_select import (
        SelectionError,
        apply_patches_to_storage_text_via_llm_view,
        parse_patches,
        patches_effect_already_present_in_storage_text,
    )

    try:
        _, key = parse_id(id)
    except ValueError as e:
        raise LensException(str(e)) from e
    if key == "_template":
        raise LensException(
            "kb_patch targets object ids, not templates; use 'lens kb template'"
        )

    local_storage: Storage | None = None
    if store is None:
        project_root = find_project_root()
        local_storage = (
            None
            if is_dataset_root(project_root)
            else Storage(find_git_root_from(project_root))
        )
        kb = (
            KnowledgeStore.for_project(project_root, storage=local_storage)
            if local_storage is not None
            else KnowledgeStore.for_project(project_root)
        )
    else:
        kb = store
    if not kb.exists(id):
        raise LensException(f"KB object not found: {id}")
    existing = kb.get_objects([id]).get(id)
    if existing is None:
        raise LensException(f"KB object not found: {id}")

    # Normalise patch list: accept Patch instances or the raw tool-call
    # dict shape understood by ``parse_patches``.
    if patches is None:
        patch_objs: list[_Patch] = []
    elif all(isinstance(p, _Patch) for p in patches):
        patch_objs = list(cast(list[_Patch], patches))
    else:
        try:
            patch_objs = parse_patches(patches)
        except SelectionError as e:
            raise LensException(f"kb_patch: {e}") from e
    if not patch_objs:
        raise LensException("kb_patch: at least one patch is required")

    if patches_effect_already_present_in_storage_text(
        existing.text,
        patch_objs,
        storage=local_storage,
        source_id=f"kb_patch:{id}",
        insert_only=True,
    ):
        return KbPatchResult(existing, "already_present")

    try:
        new_text = apply_patches_to_storage_text_via_llm_view(
            existing.text,
            patch_objs,
            storage=local_storage,
            source_id=f"kb_patch:{id}",
        )
    except SelectionError as e:
        if patches_effect_already_present_in_storage_text(
            existing.text,
            patch_objs,
            storage=local_storage,
            source_id=f"kb_patch:{id}",
        ):
            return KbPatchResult(existing, "already_present")
        raise LensException(
            f"kb_patch: {e} — target line not found; re-read the latest "
            "object body from the previous tool result"
        ) from e

    if new_text == existing.text:
        return KbPatchResult(existing, "no_changes")

    kb.store_object(id, new_text)
    refreshed = kb.get_objects([id]).get(id)
    obj = refreshed if refreshed is not None else existing
    return KbPatchResult(obj, "patched")


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


_KB_EDIT_ANN_ID = "ke"
"""Annotation id used for KB edit claim tags — simple alphanumeric to match annotation regex."""


# ---------------------------------------------------------------------------
# KB edit helpers — annotation tags for the mutation pattern
# ---------------------------------------------------------------------------


def _kb_edit_open_tag(params: dict[str, Any] | None = None) -> str:
    tag = f"[kb_edit:{_KB_EDIT_ANN_ID}"
    if not params:
        return f"{tag}]: #"
    yaml_text = yaml.dump(params, default_flow_style=False, allow_unicode=True).rstrip("\n")
    indented = re.sub(r"^", "    ", yaml_text, flags=re.MULTILINE)
    return f"{tag}\n{indented}\n]: #"


def _kb_edit_close_tag() -> str:
    return f"[/kb_edit:{_KB_EDIT_ANN_ID}]: #"


# ---------------------------------------------------------------------------
# KB edit ref helper — parse narrative slice strings like `/chapter-1 10 30`
# and return formatted ``REF[…]`` blocks for the crawl graph.
# ---------------------------------------------------------------------------


def format_kb_edit_ref(ref_str: str, project_root: Path) -> str | None:
    """Parse a narrative slice ref and return a formatted REF block.

    *ref_str* format: ``<address> <start_line> [<end_line>]``
    e.g. ``/chapter-1 10 30``, ``/chapter-1 10`` (through end of file).
    """
    parts = ref_str.strip().split(None, 2)
    if len(parts) < 2:
        return None
    addr_part = parts[0]
    try:
        start_line = int(parts[1])
        end_line = int(parts[2]) if len(parts) >= 3 else None
    except ValueError:
        return None
    try:
        addr = NarrativeAddress.parse(addr_part)
    except ValueError:
        return None
    if addr.cursor or start_line < 1:
        return None
    if end_line is not None and end_line < start_line:
        return None
    line_arg = start_line
    line_end_arg = end_line or start_line
    addr = NarrativeAddress(
        narrative=addr.narrative,
        key_path=addr.key_path,
        line=line_arg,
        line_end=line_end_arg,
    )
    try:
        resolved = resolve_address(addr, project_root)
    except ValueError:
        return None
    if resolved.cursor or resolved.narrative is None or resolved.line is None:
        return None
    node = resolved.to_node(project_root)
    if not node.exists():
        return None
    lines = node.md_path().read_text(encoding="utf-8").split("\n")
    actual_end = end_line if end_line is not None else len(lines)
    if actual_end > len(lines):
        return None
    excerpt = "\n".join(lines[resolved.line - 1 : actual_end]).rstrip()
    if not excerpt:
        return None
    # Strip markdown annotation comments so the ref behaves like crawl content
    excerpt = strip_markdown_comments(excerpt).strip()
    if not excerpt:
        return None
    # str(resolved) already includes @line:line_end; for open-ended slices
    # the label shows just the start line since the end is implicit.
    if end_line is not None:
        label = str(resolved)
    else:
        path = "/".join(resolved.key_path) if resolved.key_path else ""
        label = f"{resolved.narrative}/{path}@{resolved.line}" if path else f"{resolved.narrative}@{resolved.line}"
    return f"REF[{label!r}]\n{excerpt}\n"


# ---------------------------------------------------------------------------
# Pending claim detection for kb_edit
# ---------------------------------------------------------------------------


def _has_pending_kb_edit(file_path: Path) -> bool:
    if not file_path.exists():
        return False
    text = file_path.read_text(encoding="utf-8")
    for ann in parse_annotations(text):
        if ann.operator == "kb_edit" and ann.id == _KB_EDIT_ANN_ID and not ann.closing and not ann.self_closing:
            return True
    return False


# ---------------------------------------------------------------------------
# KB edit — mutation-based AI operator
# ---------------------------------------------------------------------------


async def kb_edit(
    id: str,
    instruction: str,
    *,
    project_root: Path | None = None,
    context_address: str | None = None,
    pins: list[str] | None = None,
    unpins: list[str] | None = None,
    include_template: bool = False,
    llm_id: str | None = None,
    reasoning: str | None = None,
    retry: bool = False,
    on_token: Callable[[str], None] | None = None,
    cancel_event: Event | None = None,
) -> None:
    """Edit or create a knowledge object using AI, with mutation pattern support.

    Fresh calls wrap the current content in claim tags (staged), generate a
    replacement via LLM, then propose it as an unstaged diff.  ``--retry``
    rolls back the proposal and re-generates.

    *context_address* can be:
      - ``/chapter-1`` — full crawl with pin resolution from the node's ancestor chain
      - ``/chapter-1 10`` — slice from line 10 to end of node (ref, no ancestor pins)
      - ``/chapter-1 10 30`` — slice lines 10–30 (ref, no ancestor pins)
    """
    if not instruction or not instruction.strip():
        raise LensException("instruction is required (AI instructions for what to write/change)")

    try:
        type_name, key = parse_id(id)
    except ValueError as e:
        raise LensException(str(e)) from e
    if key == "_template":
        raise LensException("kb edit targets object ids, not templates; use 'lens kb template'")

    if project_root is None:
        project_root = find_project_root()
    if is_dataset_root(project_root) and context_address is not None:
        raise LensException("--context is not available in dataset mode")

    local_storage = (
        None
        if is_dataset_root(project_root)
        else Storage(find_git_root_from(project_root))
    )
    kb_store = (
        KnowledgeStore.for_project(project_root, storage=local_storage)
        if local_storage is not None
        else KnowledgeStore.for_project(project_root)
    )
    file_path = project_root / "knowledge" / type_name / f"{key}.md"
    pins_list = pins or []
    unpins_list = unpins or []

    # -- resolve crawl context --
    # context_address may include optional line bounds for slice mode
    if context_address is not None:
        parts = context_address.strip().split(None, 2)
        addr = NarrativeAddress.parse(parts[0])

        if len(parts) >= 2:
            # Slice mode: inject as reference, no ancestor pin resolution
            if addr.cursor:
                raise LensException("cannot use cursor in context slice")
            ref_str = " ".join(parts)
            ref_block = format_kb_edit_ref(ref_str, project_root)
            if ref_block is None:
                raise LensException(f"invalid context slice: {context_address}")

            crawl_result = crawl_result_from_pins(
                project_root,
                pins_list,
                unpins_list,
                storage=local_storage,
            )
            crawl_result.graph.add_component(
                CrawlComponent(
                    id="kb-edit-context-slice",
                    kind="reference",
                    text=ref_block,
                    role="context",
                    source=ComponentSource(kind="operator", identifier="context_slice"),
                    priority=60,
                )
            )
        else:
            # Full crawl mode: resolve pins from ancestor chain
            resolved_addr = resolve_address(addr, project_root)
            node = resolved_addr.to_node(project_root)
            if not node.exists():
                raise LensException(f"context node does not exist: {context_address}")
            crawl_result = crawl(
                CrawlSpec.of(
                    node,
                    extra_pins=pins_list,
                    extra_unpins=unpins_list,
                    storage=local_storage,
                )
            )
    else:
        crawl_result = crawl_result_from_pins(
            project_root,
            pins_list,
            unpins_list,
            storage=local_storage,
        )

    storage = Storage(find_git_root_from(project_root))

    # -- mutation flow: fresh or retry --
    if retry:
        if not file_path.exists() or not _has_pending_kb_edit(file_path):
            raise LensException(f"no pending kb_edit transaction to retry for '{id}'")
        storage.rollback()
        text = file_path.read_text(encoding="utf-8")
        anns = parse_annotations(text)
        open_ann = None
        close_ann = None
        for a in anns:
            if a.operator == "kb_edit" and a.id == _KB_EDIT_ANN_ID:
                if not a.closing and not a.self_closing:
                    open_ann = a
                elif a.closing:
                    close_ann = a
        if open_ann is None or close_ann is None:
            raise LensException("kb_edit claim tags not found after rollback")
        lines = text.split("\n")
        existing_content = "\n".join(lines[open_ann.line_end : close_ann.line_start - 1])
    else:
        # fresh edit — get current content and wrap in claim tags
        objs = kb_store.get_objects([id])
        existing_obj = objs.get(id)
        existing_content = existing_obj.text if existing_obj else None

        open_tag = _kb_edit_open_tag()
        close_tag = _kb_edit_close_tag()
        if existing_content:
            wrapped = f"{open_tag}\n{existing_content.rstrip()}\n\n{close_tag}\n"
        else:
            wrapped = f"{open_tag}\n\n{close_tag}\n"
        storage.write_file(file_path, wrapped)
        storage.stage_all()

    template_content: str | None = None
    if include_template or existing_content is None:
        template_content = kb_store.get_template(type_name)

    messages = assemble_prompt_kb_edit(
        crawl_result,
        instruction,
        existing_content=(existing_content or None),
        template_content=template_content,
        include_template=include_template,
    )

    # -- run LLM --
    async def _on_preview(s: str) -> None:
        if on_token is not None:
            on_token(s)

    from lens.core.generation_artifacts import compose_for_operator

    bundle = build_command_tools_bundle(project_root)

    art = await run_llm(
        LlmRunRequest(
            project_root=project_root,
            messages=messages,
            tools=bundle.tools,
            command_tool_handlers=bundle.handlers,
            llm_id=llm_id,
            reasoning=reasoning,
            on_token=_on_preview if on_token is not None else None,
            on_llm_error=lambda e: LensException(str(e)),
            cancel_event=cancel_event,
        ),
    )
    new_content = compose_for_operator(art, "kb_edit")
    if not new_content.strip():
        return

    # -- propose mutation (unstaged diff) —
    # Replace the claim-block (open tag + original + close tag) with just the new content
    text = file_path.read_text(encoding="utf-8")
    anns = parse_annotations(text)
    open_ann = None
    close_ann = None
    for a in anns:
        if a.operator == "kb_edit" and a.id == _KB_EDIT_ANN_ID:
            if not a.closing and not a.self_closing:
                open_ann = a
            elif a.closing:
                close_ann = a
    if open_ann is not None and close_ann is not None:
        lines = text.split("\n")
        before = lines[: open_ann.line_start - 1]
        after = lines[close_ann.line_end :]
        rebuilt = _lines_prefix(before) + new_content.rstrip() + _lines_suffix(after)
        storage.write_file(file_path, rebuilt)


def _lines_prefix(before_lines: list[str]) -> str:
    if not before_lines:
        return ""
    return "\n".join(before_lines) + "\n"


def _lines_suffix(after_lines: list[str]) -> str:
    if not after_lines:
        return ""
    return "\n" + "\n".join(after_lines)


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

    When the same id appears in multiple blocks, entries are **merged**:
    ``tags`` and ``remove-tags`` accumulate (order-preserving dedup), and the
    last block's ``content`` wins.
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
        if entry.id in entries_by_id:
            existing = entries_by_id[entry.id]
            existing.tags = list(dict.fromkeys(existing.tags + entry.tags))
            existing.remove_tags = list(dict.fromkeys(existing.remove_tags + entry.remove_tags))
            if entry.content.strip():
                existing.content = entry.content
        else:
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
