from __future__ import annotations

import asyncio
from collections.abc import Callable

from lens.core.address import NarrativeAddress
from lens.core.context import (
    assemble_prompt_kb_edit,
    crawl,
    crawl_result_from_pins,
)
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeObject, KnowledgeStore, parse_id
from lens.core.llm import LLMError, generate_stream
from lens.core.project import find_project_root, is_dataset_root, resolve_address


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

def kb_template(type_name: str, content: str | None) -> str | None:
    kb = get_store()
    if content is not None:
        kb.set_template(type_name, content)
        return None
    return kb.get_template(type_name)

def kb_tag(id: str, add: list[str], remove: list[str]) -> tuple[list[str], list[str]]:
    try:
        parse_id(id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = get_store()
    if add:
        err = kb.add_tags(id, add)
        if err is not None:
            raise LensException(err)
    if remove:
        kb.remove_tags(id, remove)
    current = kb.get_tags(id)
    invalid = kb.get_invalid_dot_tags(current) if current else []
    return current, invalid

def kb_delete(id: str) -> None:
    try:
        parse_id(id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = get_store()
    kb.delete_object(id)


def kb_copy(source_id: str, target_id: str) -> None:
    try:
        parse_id(source_id)
        parse_id(target_id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = get_store()
    try:
        kb.copy_object(source_id, target_id)
    except ValueError as e:
        raise LensException(str(e)) from e


def kb_rename(old_id: str, new_id: str) -> None:
    try:
        parse_id(old_id)
        parse_id(new_id)
    except ValueError as e:
        raise LensException(str(e)) from e
    kb = get_store()
    try:
        kb.rename_object(old_id, new_id)
    except ValueError as e:
        raise LensException(str(e)) from e

def kb_get(ids: list[str]) -> tuple[list[str], dict[str, KnowledgeObject]]:
    kb = get_store()
    return kb.get_objects_with_links(ids)

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
