"""Front matter pin/unpin manipulation and bookkeeping for narrative nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, cast

import yaml

from lens.core.annotations import find_front_matter_span, parse_front_matter
from lens.core.narrative import NarrativeNode
from lens.core.storage import Storage

KB_PIN = "kb_pin"
KB_UNPIN = "kb_unpin"
TTS_CACHED = "tts_cached"
MODALITIES = "modalities"


def _render_front_matter(data: dict[str, Any]) -> str:
    payload = {k: v for k, v in data.items() if v}
    if not payload:
        return ""
    yaml_text = yaml.dump(payload, default_flow_style=False).rstrip("\n")
    indented = "\n".join("    " + line for line in yaml_text.split("\n"))
    return f"[\n{indented}\n]: #"


def _set_front_matter(path: Path, data: dict[str, Any], storage: Storage) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    span = find_front_matter_span(text)

    payload = {k: v for k, v in data.items() if v}
    if not payload:
        if span is not None:
            before = lines[: span[0]]
            after = lines[span[1] :]
            new_lines = before + after
            content = "\n".join(new_lines)
            storage.write_file(path, content)
        return

    block = _render_front_matter(data)
    if span is not None:
        new_lines = lines[: span[0]] + [block] + lines[span[1] :]
    else:
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        new_lines = [block, ""] + lines[i:]
    storage.write_file(path, "\n".join(new_lines))


def _mutate_front_matter(
    node: NarrativeNode,
    storage: Storage,
    fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    path = node.md_path()
    fm = parse_front_matter(path.read_text(encoding="utf-8"))
    new_fm = fn(fm)
    _set_front_matter(path, new_fm, storage)


def pin(node: NarrativeNode, kb_ids: list[str], storage: Storage) -> None:
    """Add kb_ids to kb_pin in the node's front matter."""

    def add(d: dict[str, Any]) -> dict[str, Any]:
        raw = cast(list[str], d.get(KB_PIN) or [])
        current = list(raw)
        seen = set(current)
        for kid in kb_ids:
            if kid not in seen:
                current.append(kid)
                seen.add(kid)
        out = dict(d)
        out[KB_PIN] = current
        return out

    _mutate_front_matter(node, storage, add)


def unpin(node: NarrativeNode, kb_ids: list[str], storage: Storage) -> None:
    """Add kb_ids to kb_unpin in the node's front matter."""

    def add(d: dict[str, Any]) -> dict[str, Any]:
        raw = cast(list[str], d.get(KB_UNPIN) or [])
        current = list(raw)
        seen = set(current)
        for kid in kb_ids:
            if kid not in seen:
                current.append(kid)
                seen.add(kid)
        out = dict(d)
        out[KB_UNPIN] = current
        return out

    _mutate_front_matter(node, storage, add)


def remove_pin(node: NarrativeNode, kb_ids: list[str], storage: Storage) -> None:
    """Remove kb_ids from kb_pin in the node's front matter."""

    def remove(d: dict[str, Any]) -> dict[str, Any]:
        raw = cast(list[str], d.get(KB_PIN) or [])
        current = [x for x in raw if x not in set(kb_ids)]
        out = dict(d)
        out[KB_PIN] = current
        return out

    _mutate_front_matter(node, storage, remove)


def remove_unpin(node: NarrativeNode, kb_ids: list[str], storage: Storage) -> None:
    """Remove kb_ids from kb_unpin in the node's front matter."""

    def remove(d: dict[str, Any]) -> dict[str, Any]:
        raw = cast(list[str], d.get(KB_UNPIN) or [])
        current = [x for x in raw if x not in set(kb_ids)]
        out = dict(d)
        out[KB_UNPIN] = current
        return out

    _mutate_front_matter(node, storage, remove)


def set_tts_cached_rev(node: NarrativeNode, rev: int, storage: Storage) -> None:
    """Set ``tts_cached`` in the node's front matter (chunking/cache revision)."""

    def _set(d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        out[TTS_CACHED] = rev
        return out

    _mutate_front_matter(node, storage, _set)


def set_var(node: NarrativeNode, key: str, value: str, storage: Storage) -> None:
    """Set one key in top-level ``vars`` (string values only)."""

    def _set(d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        raw = out.get("vars")
        vars_map: dict[str, str] = {}
        if isinstance(raw, dict):
            rd = cast(dict[Any, Any], raw)
            for k_raw, v_raw in rd.items():
                if not isinstance(k_raw, str):
                    continue
                vars_map[k_raw] = v_raw if isinstance(v_raw, str) else str(v_raw)
        vars_map[key] = value
        out["vars"] = vars_map
        return out

    _mutate_front_matter(node, storage, _set)


def unset_var(node: NarrativeNode, key: str, storage: Storage) -> None:
    """Remove *key* from ``vars`` on this node."""

    def _unset(d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        raw = out.get("vars")
        if not isinstance(raw, dict):
            return out
        rd = cast(dict[str, Any], raw)
        vm: dict[str, Any] = dict(rd)
        vm.pop(key, None)
        if not vm:
            out.pop("vars", None)
        else:
            out["vars"] = vm
        return out

    _mutate_front_matter(node, storage, _unset)


def set_param(node: NarrativeNode, scope: str, key: str, value: Any, storage: Storage) -> None:
    """Set ``params.<scope>[key]`` (scope is ``global`` or an operator slug)."""

    def _set(d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        raw_p = out.get("params")
        params: dict[str, Any] = {}
        if isinstance(raw_p, dict):
            pd = cast(dict[Any, Any], raw_p)
            for sk_raw, sv_raw in pd.items():
                sk = str(sk_raw)
                if isinstance(sv_raw, dict):
                    params[sk] = dict(cast(dict[str, Any], sv_raw))
                else:
                    params[sk] = sv_raw
        bucket_raw = params.get(scope)
        bucket: dict[str, Any] = (
            dict(cast(dict[str, Any], bucket_raw)) if isinstance(bucket_raw, dict) else {}
        )
        bucket[key] = value
        params[scope] = bucket
        out["params"] = params
        return out

    _mutate_front_matter(node, storage, _set)


def unset_param(node: NarrativeNode, scope: str, key: str, storage: Storage) -> None:
    """Remove *key* from ``params.<scope>`` on this node."""

    def _unset(d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        raw_p = out.get("params")
        if not isinstance(raw_p, dict):
            return out
        pd = cast(dict[Any, Any], raw_p)
        params: dict[str, Any] = {}
        for sk_raw, sv_raw in pd.items():
            sk = str(sk_raw)
            if isinstance(sv_raw, dict):
                params[sk] = dict(cast(dict[str, Any], sv_raw))
            else:
                params[sk] = sv_raw
        bucket_raw = params.get(scope)
        if not isinstance(bucket_raw, dict):
            return out
        bucket = dict(cast(dict[str, Any], bucket_raw))
        bucket.pop(key, None)
        if not bucket:
            params.pop(scope, None)
        else:
            params[scope] = bucket
        if not params:
            out.pop("params", None)
        else:
            out["params"] = params
        return out

    _mutate_front_matter(node, storage, _unset)


def set_last_compress_size(node: NarrativeNode, new_size: int, storage: Storage) -> None:
    """Write ``compress.last_size`` to *node*'s front matter through *storage*."""

    def _update(d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        compress_fm = dict(cast(dict[str, Any], out.get("compress") or {}))
        compress_fm["last_size"] = new_size
        out["compress"] = compress_fm
        return out

    _mutate_front_matter(node, storage, _update)


def _coerce_modality_flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "1", "on"):
            return True
        if low in ("false", "no", "0", "off"):
            return False
    return None


def _coerce_modality_config(value: Any) -> dict[str, Any] | None:
    """Normalize one ``modalities.<id>`` FM value to a config dict.

    A mapping is used as-is (string-keyed, non-empty keys only). A bare
    ``true``/``false`` (or boolean-ish string) is shorthand for
    ``{"enabled": <flag>}`` — the whole point being that a modality with no
    config of its own can still be toggled with a plain flag, while one that
    needs config (e.g. ``media_attach``'s ``anchor``) keeps everything about
    it, including whether it's on, in the same object instead of a second,
    separately-shaped top-level FM block.
    """
    if isinstance(value, dict):
        rd = cast(dict[Any, Any], value)
        out: dict[str, Any] = {}
        for k_raw, v in rd.items():
            k = str(k_raw).strip()
            if k:
                out[k] = v
        return out
    flag = _coerce_modality_flag(value)
    if flag is not None:
        return {"enabled": flag}
    return None


def collect_modalities_fm(node: NarrativeNode) -> dict[str, dict[str, Any]]:
    """Merged ``modalities.<id>`` config from root → *node*.

    Each modality's config is its own object; ancestors merge key-by-key
    *within* each modality's config (deeper node wins per key, not per
    modality) — this is what lets a leaf node flip ``enabled`` or set e.g.
    ``anchor`` without clobbering config set higher up the chain.
    """
    from lens.core.context import ancestor_chain

    merged: dict[str, dict[str, Any]] = {}
    for anc in ancestor_chain(node):
        if not anc.exists():
            continue
        raw = anc.front_matter().get(MODALITIES)
        if not isinstance(raw, dict):
            continue
        rd = cast(dict[Any, Any], raw)
        for key_raw, val_raw in rd.items():
            key = str(key_raw).strip()
            if not key:
                continue
            cfg = _coerce_modality_config(val_raw)
            if cfg is None:
                continue
            bucket = merged.setdefault(key, {})
            bucket.update(cfg)
    return merged


def modality_enabled(config: dict[str, Any]) -> bool:
    """Whether a merged modality config (see ``collect_modalities_fm``) is switched on.

    Presence of *any* config for a modality implies it's on — setting e.g.
    ``media_attach.anchor`` alone is enough — since ``enabled: false`` is the
    explicit, and only, opt-out.
    """
    flag = _coerce_modality_flag(config.get("enabled", True))
    return flag if flag is not None else True


def _set_modality_key(
    node: NarrativeNode, modality_id: str, key: str, value: Any, storage: Storage
) -> None:
    def _set(d: dict[str, Any]) -> dict[str, Any]:
        out = dict(d)
        raw = out.get(MODALITIES)
        modalities: dict[str, Any] = {}
        if isinstance(raw, dict):
            rd = cast(dict[Any, Any], raw)
            for k_raw, v_raw in rd.items():
                k = str(k_raw).strip()
                if k:
                    modalities[k] = v_raw
        cfg = dict(_coerce_modality_config(modalities.get(modality_id)) or {})
        if value is None or value == "":
            cfg.pop(key, None)
        else:
            cfg[key] = value
        if cfg:
            modalities[modality_id] = cfg
        else:
            modalities.pop(modality_id, None)
        if modalities:
            out[MODALITIES] = modalities
        else:
            out.pop(MODALITIES, None)
        return out

    _mutate_front_matter(node, storage, _set)


def set_modality(node: NarrativeNode, modality_id: str, enabled: bool, storage: Storage) -> None:
    """Set ``modalities.<modality_id>.enabled``, merging into any existing config for that id."""
    _set_modality_key(node, modality_id, "enabled", enabled, storage)


def set_modality_config(
    node: NarrativeNode, modality_id: str, key: str, value: Any, storage: Storage
) -> None:
    """Set one modality-specific config key (e.g. ``media_attach``'s ``anchor``)
    within ``modalities.<modality_id>``, alongside ``enabled``/other keys already
    set there. An empty string clears *key* rather than persisting it — clearing
    the last key (including ``enabled``) drops the whole ``modalities.<modality_id>``
    entry."""
    _set_modality_key(node, modality_id, key, value, storage)


def unset_modality_config(node: NarrativeNode, modality_id: str, key: str, storage: Storage) -> None:
    """Remove *key* from ``modalities.<modality_id>`` on this node."""
    _set_modality_key(node, modality_id, key, None, storage)
