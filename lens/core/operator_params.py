"""Merge pinned operator parameters from ``lens.toml`` and narrative front matter.

Front matter and TOML use a ``params`` tree: ``params.global`` and
``params.<operator_slug>`` (e.g. ``params.chat``). Keys and values must match
the same canonical names the operators use in annotations and ``extra_params``
(``llm_id``, ``reasoning``, ``as_kb_id``, …). Adapters (CLI flags, HTTP DTOs)
may use different labels but must translate before calling into this module.

The only operator-specific rule here is chat session identity: when continuing
an open chat session without explicit ``as_kb_id`` / ``with_kb_id`` in the
invocation, pinned character ids are not applied so annotation state wins.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any, cast

from lens.core.context import ancestor_chain
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession

logger = logging.getLogger(__name__)

_GLOBAL_SCOPE = "global"


def discover_param_operator_slugs(
    project_root: Path, focus_node: NarrativeNode
) -> frozenset[str]:
    slugs: set[str] = set()
    raw = load_params_toml(project_root)
    for k in raw:
        if k != _GLOBAL_SCOPE:
            slugs.add(str(k))
    for anc in ancestor_chain(focus_node):
        if not anc.exists():
            continue
        raw_p = anc.front_matter().get("params")
        if isinstance(raw_p, dict):
            p = cast(dict[str, Any], raw_p)
            for key in p:
                if key != _GLOBAL_SCOPE:
                    slugs.add(str(key))
    return frozenset(slugs)


def _apply_layer_provenance(
    merged: dict[str, tuple[str, Any]], raw_params: Any, slug: str
) -> None:
    if not isinstance(raw_params, dict):
        return
    p = cast(dict[str, Any], raw_params)
    g = p.get(_GLOBAL_SCOPE)
    if isinstance(g, dict):
        gd = cast(dict[str, Any], g)
        for k, v in gd.items():
            merged[str(k)] = (_GLOBAL_SCOPE, v)
    op = p.get(slug)
    if isinstance(op, dict):
        od = cast(dict[str, Any], op)
        for k, v in od.items():
            merged[str(k)] = (slug, v)


def collect_merged_provenance_raw(
    project_root: Path, focus_node: NarrativeNode, slug: str
) -> dict[str, tuple[str, Any]]:
    merged: dict[str, tuple[str, Any]] = {}
    _apply_layer_provenance(merged, load_params_toml(project_root), slug)
    for anc in ancestor_chain(focus_node):
        if not anc.exists():
            continue
        _apply_layer_provenance(merged, anc.front_matter().get("params"), slug)
    return merged


def json_safe_param_value(v: Any) -> Any:
    if v is None or isinstance(v, bool | int | float | str):
        return v
    return str(v)


def _param_binding_value_to_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return str(v)


def _bindings_for_slug(
    project_root: Path,
    focus_node: NarrativeNode,
    narrative_root: NarrativeNode | None,
    slug: str,
) -> list[tuple[str, str, Any]]:
    prov = collect_merged_provenance_raw(project_root, focus_node, slug)
    flat: dict[str, Any] = {k: v for k, (_, v) in prov.items()}
    normalized = normalize_pinned_values(flat)
    out: list[tuple[str, str, Any]] = []
    for name, value in normalized.items():
        scope, _raw = prov[name]
        out.append((scope, name, json_safe_param_value(value)))
    return out


def effective_param_bindings_at_cursor(
    project_root: Path,
    focus_node: NarrativeNode,
    narrative_root: NarrativeNode | None,
) -> dict[str, str]:
    """Merged params as ``\"scope:param_name\" -> string_value`` (e.g. ``global:llm_id``).

    Same merge order as :func:`collect_merged_raw`; dedupes ``(scope, name)``
    across operator slugs (values agree when the binding is global).
    """
    slugs = discover_param_operator_slugs(project_root, focus_node)
    if not slugs:
        slugs = frozenset({"write"})
    dedup: dict[tuple[str, str], Any] = {}
    for slug in sorted(slugs):
        for scope, name, value in _bindings_for_slug(
            project_root, focus_node, narrative_root, slug
        ):
            dedup[(scope, name)] = value
    out: dict[str, str] = {}
    for (scope, name), value in sorted(
        dedup.items(), key=lambda t: (t[0][0], t[0][1])
    ):
        out[f"{scope}:{name}"] = _param_binding_value_to_str(value)
    return out


def load_params_toml(project_root: Path) -> dict[str, Any]:
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return {}
    try:
        with lens_toml.open("rb") as f:
            cfg = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.debug("operator_params: skip lens.toml: %s", e)
        return {}
    raw = cfg.get("params")
    if not isinstance(raw, dict):
        return {}
    return cast(dict[str, Any], raw)


def _merge_one_node_params(
    into: dict[str, Any], raw_params: Any, slug: str
) -> None:
    if not isinstance(raw_params, dict):
        return
    p = cast(dict[str, Any], raw_params)
    g = p.get("global")
    if isinstance(g, dict):
        gd = cast(dict[str, Any], g)
        for k, v in gd.items():
            into[str(k)] = v
    op = p.get(slug)
    if isinstance(op, dict):
        od = cast(dict[str, Any], op)
        for k, v in od.items():
            into[str(k)] = v


def collect_merged_raw(
    project_root: Path, focus_node: NarrativeNode, slug: str
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    _merge_one_node_params(merged, load_params_toml(project_root), slug)
    for anc in ancestor_chain(focus_node):
        if not anc.exists():
            continue
        fm = anc.front_matter()
        _merge_one_node_params(merged, fm.get("params"), slug)
    return merged


def normalize_pinned_values(merged: dict[str, Any]) -> dict[str, Any]:
    """Drop empty strings, normalize string whitespace; pass through bool/number/object."""
    out: dict[str, Any] = {}
    for k_raw, v in merged.items():
        key = str(k_raw)
        if not key:
            continue
        nv = _coerce_merged_param_value(v)
        if nv is None and not isinstance(v, bool):
            continue
        out[key] = nv
    return out


def _coerce_merged_param_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return v


def _maybe_strip_chat_session_identity(
    slug: str,
    narrative: NarrativeNode | None,
    caller_extra: dict[str, Any] | None,
    pinned: dict[str, Any],
) -> None:
    if slug != "chat" or narrative is None:
        return
    from lens.core.operators.chat import ChatOperator

    if ChatOperator.find_active_session(narrative)[0] is None:
        return
    ep = caller_extra or {}
    if not ep.get("as_kb_id"):
        pinned.pop("as_kb_id", None)
    if not ep.get("with_kb_id"):
        pinned.pop("with_kb_id", None)


def apply_pinned_invocation(
    *,
    slug: str,
    project_root: Path,
    focus_node: NarrativeNode,
    narrative: NarrativeNode | None,
    llm_id: str | None,
    reasoning: str | None,
    extra_params: dict[str, Any] | None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Apply layers 1–4 and overlay explicit *extra_params* / scalar LLM args.

    Caller-supplied ``llm_id``, ``reasoning``, and keys in ``extra_params``
    win over pinned values. Returns effective ``llm_id``, ``reasoning``, and
    merged ``extra_params`` (may be empty).
    """
    raw = collect_merged_raw(project_root, focus_node, slug)
    pinned = normalize_pinned_values(raw)
    caller_extra = dict(extra_params) if extra_params else {}
    _maybe_strip_chat_session_identity(slug, narrative, caller_extra, pinned)

    eff_llm = llm_id if llm_id is not None else pinned.get("llm_id")
    eff_reasoning = reasoning if reasoning is not None else pinned.get("reasoning")
    pinned.pop("llm_id", None)
    pinned.pop("reasoning", None)

    merged_extra = {**pinned, **caller_extra}
    return eff_llm, eff_reasoning, merged_extra


def prepare_chat_invocation(
    session: ProjectSession,
    narrative: NarrativeNode,
    *,
    llm_id: str | None,
    reasoning: str | None,
    extra_params: dict[str, Any],
) -> tuple[str | None, str | None, dict[str, Any]]:
    """CLI/API preprocessor so fresh chat sessions inherit pinned params.

    Chat continue/end also run :func:`apply_pinned_invocation` inside
    :meth:`~lens.core.operators.session.SessionOperator.run_session`; that
    second pass is redundant but idempotent (explicit caller args win).
    """
    return apply_pinned_invocation(
        slug="chat",
        project_root=session.project_root,
        focus_node=narrative.find_cursor(),
        narrative=narrative,
        llm_id=llm_id,
        reasoning=reasoning,
        extra_params=extra_params,
    )


def chat_invocation_uses_session(
    *, end: bool, extra_params: dict[str, Any] | None
) -> bool:
    """Whether a chat invocation should use session mode after pinned params merge."""
    if end:
        return True
    if not extra_params:
        return False
    return extra_params.get("with_kb_id") is not None
