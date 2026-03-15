from __future__ import annotations

from dataclasses import dataclass, field

from lens.core.address import NarrativeAddress
from lens.core.context import crawl_pins
from lens.core.project import ProjectSession, get_mount_point, get_selected_datasets, is_dataset_root, list_available_llms
from lens.core.knowledge import KnowledgeStore


@dataclass
class StatsResult:
    kb_types: list[str]
    kb_count: int
    trees: list[tuple[str, int]]
    cursor_addr: NarrativeAddress | None
    has_pending: bool
    pending_owner: NarrativeAddress | None
    dataset_name: str | None = None
    current_datasets: list[str] = field(default_factory=list[str])
    pending_diff: str = field(default="")
    staged_diff: str = field(default="")
    effective_pins_at_cursor: list[str] = field(default_factory=list[str])
    available_llms: list[str] = field(default_factory=list[str])
    has_mount: bool = False


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
    if not is_dataset and cursor_addr is not None:
        node_addr = cursor_addr.node_only()
        try:
            node = node_addr.to_node(root)
        except ValueError:
            node = None  # type: ignore[assignment]
        if node is not None:
            effective_pins_at_cursor = crawl_pins(node)

    available_llms = list_available_llms(root)
    has_mount = get_mount_point(root) is not None

    return StatsResult(
        kb_types=kb_types,
        kb_count=kb_count,
        trees=trees,
        cursor_addr=cursor_addr,
        has_pending=has_pending,
        pending_owner=pending_owner,
        dataset_name=root.name if is_dataset else None,
        current_datasets=current_datasets,
        pending_diff=pending_diff,
        staged_diff=staged_diff,
        effective_pins_at_cursor=effective_pins_at_cursor,
        available_llms=available_llms,
        has_mount=has_mount,
    )
