from __future__ import annotations

from pathlib import Path

from lens.core.address import NarrativeAddress
from lens.core.knowledge import parse_id
from lens.core.narrative import NarrativeNode
from lens.core.pinning import pin, remove_pin, remove_unpin, unpin
from lens.core.project import get_active_narrative, require_lens_context
from lens.core.storage import Storage
from lens.core.exceptions import LensException


def resolve_node(cwd: Path, node_arg: str | None) -> tuple[Path, Path, NarrativeNode]:
    try:
        git_root, project_root = require_lens_context(cwd)
    except RuntimeError as e:
        raise LensException(str(e)) from e

    addr = NarrativeAddress.parse(node_arg or "/@cursor")
    if addr.cursor or addr.narrative is None:
        narrative = get_active_narrative(project_root)
        if narrative is None:
            raise LensException("no active narrative (run 'lens use <slug>' first)")
        if addr.cursor:
            return git_root, project_root, narrative.find_cursor()
        addr = addr.with_narrative(narrative.narrative_root.name)
    return git_root, project_root, addr.to_node(project_root)


def collect_ids(id: str | None, extra_ids: list[str]) -> list[str]:
    return ([id] if id else []) + list(extra_ids)


def validate_ids(ids: list[str]) -> None:
    invalid: list[str] = []
    for kid in ids:
        try:
            parse_id(kid)
        except ValueError:
            invalid.append(kid)
    if invalid:
        raise LensException(f"invalid ID(s): {', '.join(invalid)}")


def pin_add(cwd: Path, id: str | None, node_pos: str | None, extra_ids: list[str], node_opt: str | None) -> tuple[int, str]:
    all_ids = collect_ids(id, extra_ids)
    if not all_ids:
        raise LensException("provide at least one knowledge object ID (type.key)")
    validate_ids(all_ids)
    try:
        git_root, _project_root, target = resolve_node(cwd, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = Storage(git_root, owner=None)
    pin(target, all_ids, storage)
    return len(all_ids), target.path_str()


def pin_remove(cwd: Path, id: str | None, node_pos: str | None, extra_ids: list[str], node_opt: str | None) -> tuple[int, str]:
    all_ids = collect_ids(id, extra_ids)
    if not all_ids:
        raise LensException("provide at least one knowledge object ID (type.key)")
    validate_ids(all_ids)
    try:
        git_root, _project_root, target = resolve_node(cwd, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = Storage(git_root, owner=None)
    remove_pin(target, all_ids, storage)
    return len(all_ids), target.path_str()


def pin_block(cwd: Path, id: str | None, node_pos: str | None, extra_ids: list[str], node_opt: str | None) -> tuple[int, str]:
    all_ids = collect_ids(id, extra_ids)
    if not all_ids:
        raise LensException("provide at least one knowledge object ID (type.key)")
    validate_ids(all_ids)
    try:
        git_root, _project_root, target = resolve_node(cwd, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = Storage(git_root, owner=None)
    unpin(target, all_ids, storage)
    return len(all_ids), target.path_str()


def pin_unblock(cwd: Path, id: str | None, node_pos: str | None, extra_ids: list[str], node_opt: str | None) -> tuple[int, str]:
    all_ids = collect_ids(id, extra_ids)
    if not all_ids:
        raise LensException("provide at least one knowledge object ID (type.key)")
    validate_ids(all_ids)
    try:
        git_root, _project_root, target = resolve_node(cwd, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = Storage(git_root, owner=None)
    remove_unpin(target, all_ids, storage)
    return len(all_ids), target.path_str()
