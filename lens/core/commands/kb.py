from __future__ import annotations

from lens.core.knowledge import KnowledgeObject, KnowledgeStore, parse_id
from lens.core.project import find_project_root
from lens.core.exceptions import LensException

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
