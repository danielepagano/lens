from __future__ import annotations

from typing import Any

from lens.core.address import NarrativeAddress
from lens.core.knowledge import parse_id
from lens.core.narrative import NarrativeNode
from lens.core.pinning import (
    pin,
    remove_pin,
    remove_unpin,
    set_param,
    set_var,
    unpin,
    unset_param,
    unset_var,
)
from lens.core.project import ProjectSession, validate_slug
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


_PARAM_SCOPE_GLOBAL = "global"


def coerce_param_pin_value(text: str) -> Any:
    s = text.strip()
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(s, 10)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def normalize_param_pin_value(value: Any) -> Any:
    if isinstance(value, str):
        return coerce_param_pin_value(value)
    if value is None:
        return None
    return value


def var_value_to_parts(value: Any) -> list[str]:
    if isinstance(value, bool):
        return ["true" if value else "false"]
    if isinstance(value, str):
        return [value]
    return [str(value)]


def validate_var_key(key: str) -> None:
    k = key.strip()
    if not k:
        raise LensException("var key cannot be empty")


def validate_param_scope(scope: str) -> str:
    s = scope.strip()
    if not s:
        raise LensException("param scope cannot be empty")
    if s == _PARAM_SCOPE_GLOBAL:
        return _PARAM_SCOPE_GLOBAL
    if validate_slug(s):
        return s
    raise LensException(
        f"invalid param scope '{scope}' (use 'global' or an operator slug: letters, digits, _ -)"
    )


def validate_param_key(key: str) -> None:
    k = key.strip()
    if not k:
        raise LensException("param key cannot be empty")


def validate_ids(ids: list[str]) -> None:
    invalid: list[str] = []
    for kid in ids:
        # Allow knowledge IDs to be suffixed with '+' / '++' to request linked expansion
        # later during crawl (the front matter preserves the suffix).
        base = kid[:-2] if kid.endswith("++") else (kid[:-1] if kid.endswith("+") else kid)
        # Reject any other trailing '+' patterns like 'id+++'.
        if base.endswith("+"):
            invalid.append(kid)
            continue
        try:
            parse_id(base)
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


def var_set(
    session: ProjectSession,
    key: str,
    value_parts: list[str],
    node_pos: str | None,
    node_opt: str | None,
) -> tuple[int, str]:
    validate_var_key(key)
    value = " ".join(value_parts).strip() if value_parts else ""
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    set_var(target, key.strip(), value, storage)
    return 1, target.path_str()


def var_unset(
    session: ProjectSession,
    key: str,
    node_pos: str | None,
    node_opt: str | None,
) -> tuple[int, str]:
    validate_var_key(key)
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    unset_var(target, key.strip(), storage)
    return 1, target.path_str()


def param_set(
    session: ProjectSession,
    scope: str,
    key: str,
    value_parts: list[str],
    node_pos: str | None,
    node_opt: str | None,
) -> tuple[int, str]:
    sc = validate_param_scope(scope)
    validate_param_key(key)
    raw = " ".join(value_parts).strip() if value_parts else ""
    val = coerce_param_pin_value(raw) if raw else ""
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    set_param(target, sc, key.strip(), val, storage)
    return 1, target.path_str()


def param_unset(
    session: ProjectSession,
    scope: str,
    key: str,
    node_pos: str | None,
    node_opt: str | None,
) -> tuple[int, str]:
    sc = validate_param_scope(scope)
    validate_param_key(key)
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    unset_param(target, sc, key.strip(), storage)
    return 1, target.path_str()


def param_set_value(
    session: ProjectSession,
    scope: str,
    key: str,
    value: Any,
    node_pos: str | None,
    node_opt: str | None,
) -> tuple[int, str]:
    """Like ``param_set`` but with a structured *value* (e.g. from JSON)."""
    sc = validate_param_scope(scope)
    validate_param_key(key)
    val = normalize_param_pin_value(value)
    try:
        target = resolve_node(session, node_pos or node_opt)
    except (RuntimeError, ValueError) as e:
        raise LensException(str(e)) from e
    storage = session.new_storage(owner=None)
    set_param(target, sc, key.strip(), val, storage)
    return 1, target.path_str()
