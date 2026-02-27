from __future__ import annotations

from lens.core.address import NarrativeAddress
from lens.core.knowledge import parse_id
from lens.core.narrative import NarrativeNode
from lens.core.pinning import pin, remove_pin, remove_unpin, unpin
from lens.core.project import ProjectSession
from lens.core.exceptions import LensException


def resolve_node(session: ProjectSession, node_arg: str | None) -> NarrativeNode:
    addr = NarrativeAddress.parse(node_arg or "/@cursor")
    narrative = session.active_narrative
    if addr.cursor or addr.narrative is None:
        if narrative is None:
            raise LensException("no active narrative (run 'lens use <slug>' first)")
        if addr.cursor:
            return narrative.find_cursor()
        addr = addr.with_narrative(narrative.narrative_root.name)
    return addr.to_node(session.project_root)


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


def pin_add(session: ProjectSession, id: str | None, node_pos: str | None, extra_ids: list[str], node_opt: str | None) -> tuple[int, str]:
    all_ids = collect_ids(id, extra_ids)
    if not all_ids:
        raise LensException("provide at least one knowledge object ID (type.key)")
    validate_ids(all_ids)
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    pin(target, all_ids, storage)
    return len(all_ids), target.path_str()


def pin_remove(session: ProjectSession, id: str | None, node_pos: str | None, extra_ids: list[str], node_opt: str | None) -> tuple[int, str]:
    all_ids = collect_ids(id, extra_ids)
    if not all_ids:
        raise LensException("provide at least one knowledge object ID (type.key)")
    validate_ids(all_ids)
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    remove_pin(target, all_ids, storage)
    return len(all_ids), target.path_str()


def pin_block(session: ProjectSession, id: str | None, node_pos: str | None, extra_ids: list[str], node_opt: str | None) -> tuple[int, str]:
    all_ids = collect_ids(id, extra_ids)
    if not all_ids:
        raise LensException("provide at least one knowledge object ID (type.key)")
    validate_ids(all_ids)
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    unpin(target, all_ids, storage)
    return len(all_ids), target.path_str()


def pin_unblock(session: ProjectSession, id: str | None, node_pos: str | None, extra_ids: list[str], node_opt: str | None) -> tuple[int, str]:
    all_ids = collect_ids(id, extra_ids)
    if not all_ids:
        raise LensException("provide at least one knowledge object ID (type.key)")
    validate_ids(all_ids)
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    remove_unpin(target, all_ids, storage)
    return len(all_ids), target.path_str()
