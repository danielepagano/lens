from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lens.core.exceptions import LensException
from lens.core.project import (
    find_project_root,
    get_selected_prompt_pack,
    set_selected_prompt_pack,
)
from lens.core.prompts import (
    PromptStore,
    default_prompts_file,
    project_prompts_file,
    prompt_pack_file,
    prompts_root,
)


@dataclass(frozen=True)
class PromptRecord:
    key: str
    source: str
    value: str


def get_prompt_store() -> tuple[Path, PromptStore]:
    try:
        project_root = find_project_root()
    except RuntimeError as e:
        raise LensException(str(e)) from e
    return project_root, PromptStore(project_root)


def prompt_list(operator: str | None = None) -> list[str]:
    _project_root, store = get_prompt_store()
    return store.list_keys(operator=operator)


def prompt_get(key: str) -> PromptRecord:
    _project_root, store = get_prompt_store()
    try:
        resolved = store.resolve(key)
    except ValueError as e:
        raise LensException(str(e)) from e
    return PromptRecord(key=resolved.key, source=resolved.source, value=resolved.value)


def prompt_set(key: str, value: str) -> Path:
    project_root, store = get_prompt_store()
    try:
        store.set_project_override(key, value)
    except ValueError as e:
        raise LensException(str(e)) from e
    return project_prompts_file(project_root)


def prompt_clear(key: str) -> Path:
    project_root, store = get_prompt_store()
    try:
        store.clear_project_override(key)
    except ValueError as e:
        raise LensException(str(e)) from e
    return project_prompts_file(project_root)


def prompt_path() -> Path:
    project_root, _store = get_prompt_store()
    return project_prompts_file(project_root)


def prompt_packs() -> list[str]:
    packs_dir = prompts_root() / "packs"
    if not packs_dir.exists():
        return []
    return sorted(path.stem for path in packs_dir.glob("*.toml"))


def prompt_pack_get() -> str | None:
    try:
        project_root = find_project_root()
    except RuntimeError as e:
        raise LensException(str(e)) from e
    return get_selected_prompt_pack(project_root)


def prompt_pack_set(pack_name: str | None) -> None:
    try:
        project_root = find_project_root()
    except RuntimeError as e:
        raise LensException(str(e)) from e
    if pack_name is not None and not prompt_pack_file(pack_name).exists():
        raise LensException(f"prompt pack does not exist: {pack_name}")
    set_selected_prompt_pack(project_root, pack_name)


def builtin_prompts_path() -> Path:
    return default_prompts_file()
