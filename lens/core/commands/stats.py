from __future__ import annotations

from dataclasses import dataclass, field
from lens.core.address import NarrativeAddress
from lens.core.annotations import parse_annotations
from lens.core.context import crawl_pins
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.project import ProjectSession, has_mount_config, get_selected_datasets, is_dataset_root, list_available_llms
from lens.core.knowledge import KnowledgeStore

SESSION_OPERATOR_NAMES: frozenset[str] = frozenset(
    {"advance", "chat", "design", "play"}
)

_REMEMBER_TAG_PREFIX = "remember."


def _chat_parent_session_extra_pins(node: NarrativeNode) -> list[str]:
    """KB ids from the parent ``[chat:…]`` annotation (as / with).

    These are merged into crawl ``extra_pins`` so ``effective_pins_at_cursor``
    matches what the chat operator treats as effective context, not only
    ``kb_pin`` front matter.
    """
    if not node.key_path:
        return []
    session_id = node.key_path[-1]
    parent = NarrativeNode(
        narrative_root=node.narrative_root,
        key_path=node.key_path[:-1],
    )
    if not parent.exists():
        return []
    try:
        text = parent.md_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    for ann in reversed(parse_annotations(text)):
        if (
            ann.operator == "chat"
            and ann.id == session_id
            and not ann.closing
            and not ann.self_closing
        ):
            out: list[str] = []
            p = ann.params
            for key in ("as_kb_id", "with_kb_id"):
                v = p.get(key)
                if isinstance(v, str) and v.strip():
                    out.append(v.strip())
            return out
    return []


def _empty_remember_pins() -> dict[str, list[str]]:
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
    available_llms: list[str] = field(default_factory=list[str])
    has_mount: bool = False
    active_session_operator: str | None = None


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

    effective_pins_at_cursor: list[str] = []
    remember_pins_at_cursor: dict[str, list[str]] = {}
    active_session_operator: str | None = None
    if not is_dataset and cursor_addr is not None:
        node_addr = cursor_addr.node_only()
        try:
            node = node_addr.to_node(root)
        except ValueError:
            node = None  # type: ignore[assignment]
        if node is not None:
            chat_extras = _chat_parent_session_extra_pins(node)
            effective_pins_at_cursor = crawl_pins(
                node,
                extra_pins=chat_extras if chat_extras else None,
            )
            for pin_id in effective_pins_at_cursor:
                remember_tags = [
                    t
                    for t in kb_store.get_tags(pin_id)
                    if t.startswith(_REMEMBER_TAG_PREFIX)
                ]
                if remember_tags:
                    remember_pins_at_cursor[pin_id] = remember_tags
            if node.key_path:
                parent = NarrativeNode(
                    narrative_root=node.narrative_root,
                    key_path=node.key_path[:-1],
                )
                try:
                    parent_text = parent.md_path().read_text(encoding="utf-8")
                    open_ann = find_unclosed_cursor_annotation(parent_text)
                    if open_ann is not None and open_ann.operator in SESSION_OPERATOR_NAMES:
                        active_session_operator = open_ann.operator
                except FileNotFoundError:
                    pass

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
        effective_pins_at_cursor=effective_pins_at_cursor,
        remember_pins_at_cursor=remember_pins_at_cursor,
        available_llms=list_available_llms(root),
        has_mount=has_mount_config(root),
        active_session_operator=active_session_operator,
    )
