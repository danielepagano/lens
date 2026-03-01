from __future__ import annotations

from dataclasses import dataclass, field

from lens.core.address import NarrativeAddress
from lens.core.project import ProjectSession, is_dataset_root


@dataclass
class StatsResult:
    type_count: int
    kb_count: int
    trees: list[tuple[str, int]]
    cursor_addr: NarrativeAddress | None
    has_pending: bool
    pending_owner: NarrativeAddress | None
    dataset_name: str | None = None
    pending_diff: str = field(default="")
    staged_diff: str = field(default="")


def get_stats(session: ProjectSession, *, verbose: bool = False) -> StatsResult:
    root = session.project_root
    is_dataset = is_dataset_root(root)
    knowledge = root / "knowledge"
    kb_count = (
        sum(1 for p in knowledge.rglob("*.md") if p.name != "_template.md")
        if knowledge.exists()
        else 0
    )
    type_count = sum(1 for d in knowledge.iterdir() if d.is_dir()) if knowledge.exists() else 0

    narrative = root / "narrative"
    trees: list[tuple[str, int]] = []
    if not is_dataset and narrative.exists():
        for d in sorted(narrative.iterdir()):
            if d.is_dir():
                node_count = sum(1 for _ in d.rglob("*.md"))
                trees.append((d.name, node_count))

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

    return StatsResult(
        type_count=type_count,
        kb_count=kb_count,
        trees=trees,
        cursor_addr=cursor_addr,
        has_pending=has_pending,
        pending_owner=pending_owner,
        dataset_name=root.name if is_dataset else None,
        pending_diff=pending_diff,
        staged_diff=staged_diff,
    )
