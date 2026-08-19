from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lens.core.address import NarrativeAddress
from lens.core.context import CrawlSpec, collect_vars, crawl
from lens.core.crawl_transforms import is_state_tags
from lens.core.modalities.bootstrap import ensure_modalities_registered
from lens.core.modalities.registry import registered_ids
from lens.core.modalities.resolve import resolve_modalities
from lens.core.modalities.types import ModalityContext
from lens.core.mentions import INCLUDE, live_mentions
from lens.core.narrative import NarrativeNode
from lens.core.operator import Operator
from lens.core.operator_detect import (
    detect_open_session_operator,
    detect_operator_name,
)
from lens.core.operator_params import collect_merged_raw, effective_param_bindings_at_cursor
from lens.core.operators import get_operator_class_for_name
from lens.core.image.registry import list_image_backend_rows
from lens.core.pinning import collect_modalities_fm
from lens.core.project import (
    ProjectSession,
    get_selected_datasets,
    has_mount_config,
    is_cloud_mount_config,
    is_dataset_root,
    list_available_llms,
)
from lens.core.dataset_config import get_dataset_configs
from lens.core.knowledge import KnowledgeStore
from lens.core.release.config import (
    parse_dataset_repo_configs,
    parse_release_config,
)
from lens.core.release.version import installed_version
from lens.core.speech import registry as speech_registry

def _empty_remember_pins() -> dict[str, list[str]]:
    return {}


def _empty_image_backends() -> list[dict[str, Any]]:
    return []


def _empty_modalities_config() -> dict[str, dict[str, Any]]:
    return {}


@dataclass
class StatsResult:
    kb_types: list[str]
    kb_count: int
    trees: list[tuple[str, int]]
    cursor_addr: NarrativeAddress | None
    has_pending: bool
    has_staged: bool
    pending_owner: NarrativeAddress | None
    dataset_name: str | None = None
    current_datasets: list[str] = field(default_factory=list[str])
    pending_diff: str = field(default="")
    staged_diff: str = field(default="")
    effective_pins_at_cursor: list[str] = field(default_factory=list[str])
    remember_pins_at_cursor: dict[str, list[str]] = field(default_factory=_empty_remember_pins)
    state_pins_at_cursor: list[str] = field(default_factory=list[str])
    include_ids_at_cursor: list[str] = field(default_factory=list[str])
    mention_ids_at_cursor: list[str] = field(default_factory=list[str])
    available_llms: list[str] = field(default_factory=list[str])
    image_backends: list[dict[str, Any]] = field(default_factory=_empty_image_backends)
    has_mount: bool = False
    cloud_mount: bool = False
    reference_images_supported: bool = False
    tts_available: bool = False
    active_session_operator: str | None = None
    effective_vars_at_cursor: dict[str, str] = field(default_factory=dict[str, str])
    effective_params_at_cursor: dict[str, str] = field(default_factory=dict[str, str])
    registered_modality_ids: list[str] = field(default_factory=list[str])
    modalities_at_cursor: dict[str, dict[str, Any]] = field(
        default_factory=_empty_modalities_config
    )
    dataset_configs: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    release_enabled: bool = False
    release_lens_repo_url: str = ""
    release_requested_version: str = ""
    release_requested_from_commit: str = ""
    release_app_leader: bool = False
    release_installed_version: str | None = None
    release_dataset_repos: list[dict[str, str]] = field(default_factory=list[dict[str, str]])


def _scoped_ids_at_cursor(node: NarrativeNode) -> tuple[list[str], list[str]]:
    """``(include ids, mention ids)`` still expanding in *node*, in written order.

    Reported separately from ``effective_pins_at_cursor`` because they are a
    different scope: node-local, never inherited, and — for mentions — good for
    one more assistant turn.  See :mod:`lens.core.mentions`.
    """
    if not node.exists():
        return [], []
    raw = node.md_path().read_text(encoding="utf-8")
    includes: list[str] = []
    mentions: list[str] = []
    for ref in live_mentions(raw):
        bucket = includes if ref.kind == INCLUDE else mentions
        if ref.kb_id not in bucket:
            bucket.append(ref.kb_id)
    return includes, mentions


def _state_tagged_ids(kb_store: KnowledgeStore, ids: list[str]) -> list[str]:
    """Which of *ids* carry the `state` tag, canonical id, in given order.

    ``pin_crawl.state_pins`` only sees pinned objects — includes and mentions
    never become pins (see :mod:`lens.core.mentions`), so a `state`-tagged
    include/mention is otherwise invisible to ``state_pins_at_cursor`` even
    though :func:`~lens.core.context._add_mention_state_components` diverts it
    into ``[LIVE STATE]`` for the real prompt just the same.
    """
    if not ids:
        return []
    objects = kb_store.get_objects(ids)
    result: list[str] = []
    for kid in ids:
        obj = objects.get(kid) or objects.get(kid.lower())
        if obj is not None and is_state_tags(obj.tags):
            result.append(obj.id)
    return result


def _operator_context_at_cursor(
    root: Path,
    node: NarrativeNode,
    *,
    operator_name: str | None,
) -> tuple[type[Any], dict[str, Any]]:
    if operator_name:
        op_cls = get_operator_class_for_name(operator_name)
        if op_cls is not None:
            return op_cls, collect_merged_raw(root, node, operator_name)
    return Operator, {}


def _resolve_modalities_at_cursor(
    session: ProjectSession,
    node: NarrativeNode,
    *,
    operator_name: str | None,
) -> dict[str, dict[str, Any]]:
    """One entry per modality that was either configured in front matter or
    considered as a candidate (builtin/required/opted-in): its merged FM
    config, whether it's active, and — if not — why.

    Replaces the old three-field split (``modalities_at_cursor`` /
    ``modality_warnings_at_cursor`` / ``effective_modalities_at_cursor``),
    which required cross-referencing by id to answer "is this on, and why
    not" for any one modality.

    *operator_name* is what would run at the cursor
    (:func:`~lens.core.operator_detect.detect_operator_name`), not merely what
    session is open: a finished inline ``play`` turn still resolves its
    modalities against ``play``.
    """
    root = session.project_root
    op_cls, params = _operator_context_at_cursor(
        root, node, operator_name=operator_name
    )
    ctx = ModalityContext(
        session=session,
        narrative=node,
        focus_node=node,
        operator_name=str(getattr(op_cls, "name", "")),
        crawl_result=None,
        params=dict(params),
        project_root=root,
    )
    resolved, _prepared_ctx = resolve_modalities(
        op_cls, node, params=params, ctx=ctx
    )
    fm_configs = collect_modalities_fm(node)
    merged: dict[str, dict[str, Any]] = {}
    for modality_id, gate in resolved.resolution.items():
        entry: dict[str, Any] = {
            "config": fm_configs.get(modality_id, {}),
            "active": gate.active,
        }
        if gate.reason:
            entry["reason"] = gate.reason
        merged[modality_id] = entry
    for modality_id, config in fm_configs.items():
        if modality_id in merged:
            continue
        # Explicit FM opt-out (enabled: false) is dropped before candidate
        # resolution, so it never reaches `resolved.resolution` above.
        merged[modality_id] = {
            "config": config,
            "active": False,
            "reason": "disabled (modalities.<id>.enabled: false)",
        }
    return merged


def get_stats(session: ProjectSession, *, verbose: bool = False) -> StatsResult:
    root = session.project_root
    is_dataset = is_dataset_root(root)
    kb_types: list[str] = []
    kb_count = 0
    kb_store = KnowledgeStore.for_project(root)
    kb_types = kb_store.list_types()
    # list_ids returns all canonical IDs (across project + datasets or dataset-only),
    # excluding templates.
    kb_count = len(kb_store.list_ids())

    narrative = root / "narrative"
    trees: list[tuple[str, int]] = []
    if not is_dataset and narrative.exists():
        for d in sorted(narrative.iterdir()):
            if d.is_dir():
                node_count = sum(1 for _ in d.rglob("*.md"))
                trees.append((d.name, node_count))
    current_datasets: list[str] = []
    if not is_dataset:
        current_datasets = get_selected_datasets(root)

    dataset_configs: dict[str, dict[str, Any]] = {}
    if not is_dataset:
        dataset_configs = get_dataset_configs(root)

    active = session.active_narrative
    cursor_addr = (
        (active.find_cursor_address() if active is not None else None)
        if not is_dataset
        else None
    )

    storage = session.new_storage()
    has_pending = storage.has_pending()
    pending_owner = storage.detect_pending_owner() if has_pending else None

    pending_diff = ""
    staged_diff = ""
    if verbose:
        pending_diff = storage.pending_diff()
        staged_diff = storage.staged_diff()

    ensure_modalities_registered()
    registered_modality_ids = sorted(registered_ids())

    effective_pins_at_cursor: list[str] = []
    remember_pins_at_cursor: dict[str, list[str]] = {}
    state_pins_at_cursor: list[str] = []
    include_ids_at_cursor: list[str] = []
    mention_ids_at_cursor: list[str] = []
    active_session_operator: str | None = None
    effective_vars_at_cursor: dict[str, str] = {}
    effective_params_at_cursor: dict[str, str] = {}
    modalities_at_cursor: dict[str, dict[str, Any]] = {}
    if not is_dataset and cursor_addr is not None:
        node_addr = cursor_addr.node_only()
        try:
            node = node_addr.to_node(root)
        except ValueError:
            node = None  # type: ignore[assignment]
        if node is not None:
            pin_crawl = crawl(CrawlSpec.of(node, include_narrative=False))
            effective_pins_at_cursor = pin_crawl.pinned_ids
            remember_pins_at_cursor = pin_crawl.remember_pins
            state_pins_at_cursor = pin_crawl.state_pins
            # A separate scan: the pin crawl above runs with
            # `include_narrative=False`, and mentions live in the node body.
            # Only the live ones — an expired mention stays in the text (that
            # is what makes rewind work) but is no longer in scope.
            include_ids_at_cursor, mention_ids_at_cursor = _scoped_ids_at_cursor(node)
            for kid in _state_tagged_ids(
                kb_store, [*include_ids_at_cursor, *mention_ids_at_cursor]
            ):
                if kid not in state_pins_at_cursor:
                    state_pins_at_cursor.append(kid)
            effective_vars_at_cursor = dict(collect_vars(node))
            effective_params_at_cursor = effective_param_bindings_at_cursor(
                root, node, active
            )
            # Two different questions (see lens.core.operator_detect): the UI
            # gates session-close affordances on an *open* session, while
            # modality resolution wants whatever would actually run here —
            # including a ``play`` turn that has already closed.
            active_session_operator = detect_open_session_operator(node)
            modalities_at_cursor = _resolve_modalities_at_cursor(
                session,
                node,
                operator_name=detect_operator_name(node),
            )

    image_backends = list_image_backend_rows(root)
    reference_images_supported = any(
        bool(row.get("supports_reference_images")) for row in image_backends
    )

    has_m = has_mount_config(root)
    tts_available = has_m and speech_registry.is_speech_backend_ready(root)

    release_cfg = parse_release_config({})
    release_repos: list[dict[str, str]] = []
    release_installed_version: str | None = None
    if not is_dataset:
        raw_config: dict[str, Any] = {}
        lens_toml = root / "lens.toml"
        if lens_toml.exists():
            with lens_toml.open("rb") as f:
                raw_config = tomllib.load(f)
        release_cfg = parse_release_config(raw_config)
        release_installed_version = installed_version()
        release_repos = []
        for r in parse_dataset_repo_configs(raw_config):
            repo_info: dict[str, str] = {
                "name": r.name,
                "git_url": r.git_url,
                "ref": r.ref,
            }
            release_repos.append(repo_info)

    return StatsResult(
        kb_types=kb_types,
        kb_count=kb_count,
        trees=trees,
        cursor_addr=cursor_addr,
        has_pending=has_pending,
        has_staged=storage.has_staged(),
        pending_owner=pending_owner,
        dataset_name=root.name if is_dataset else None,
        current_datasets=current_datasets,
        pending_diff=pending_diff,
        staged_diff=staged_diff,
        include_ids_at_cursor=include_ids_at_cursor,
        mention_ids_at_cursor=mention_ids_at_cursor,
        effective_pins_at_cursor=effective_pins_at_cursor,
        remember_pins_at_cursor=remember_pins_at_cursor,
        state_pins_at_cursor=state_pins_at_cursor,
        available_llms=list_available_llms(root),
        image_backends=image_backends,
        has_mount=has_m,
        cloud_mount=is_cloud_mount_config(root),
        reference_images_supported=reference_images_supported,
        tts_available=tts_available,
        active_session_operator=active_session_operator,
        effective_vars_at_cursor=effective_vars_at_cursor,
        effective_params_at_cursor=effective_params_at_cursor,
        registered_modality_ids=registered_modality_ids,
        modalities_at_cursor=modalities_at_cursor,
        dataset_configs=dataset_configs,
        release_enabled=release_cfg.enabled,
        release_lens_repo_url=release_cfg.lens_repo_url,
        release_requested_version=release_cfg.requested_version,
        release_requested_from_commit=release_cfg.requested_from_commit,
        release_app_leader=release_cfg.app_leader,
        release_installed_version=release_installed_version,
        release_dataset_repos=release_repos,
    )
