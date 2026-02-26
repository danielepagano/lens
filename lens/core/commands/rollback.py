from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lens.core.annotations import parse_annotations
from lens.core.project import require_lens_context
from lens.core.storage import Storage
from lens.core.exceptions import LensException

if TYPE_CHECKING:
    from lens.core.address import NarrativeAddress

@dataclass
class RollbackStatus:
    has_pending: bool
    owner: NarrativeAddress | None
    is_mutation: bool

def check_rollback_status(cwd: Path) -> RollbackStatus:
    try:
        git_root, _ = require_lens_context(cwd)
    except RuntimeError as e:
        raise LensException(str(e)) from e

    storage = Storage(git_root)
    has_pending = storage.has_pending()
    owner = storage.detect_pending_owner() if has_pending else None
    is_mutation = owner is not None and owner.operator == "edit"
    return RollbackStatus(has_pending, owner, is_mutation)

def execute_rollback(cwd: Path) -> None:
    try:
        git_root, project_root = require_lens_context(cwd)
    except RuntimeError as e:
        raise LensException(str(e)) from e

    storage = Storage(git_root)
    owner = storage.detect_pending_owner()
    is_mutation = owner is not None and owner.operator == "edit"

    if is_mutation:
        assert owner is not None
        compensating_rollback(storage, owner, project_root)
    else:
        storage.rollback()

def compensating_rollback(
    storage: Storage,
    owner: NarrativeAddress,
    project_root: Path,
) -> None:
    """Apply the compensating transaction for a pending mutation proposal."""
    storage.rollback()  # working tree ← staged (claim tags are now present)

    ann_id = owner.op_id
    assert ann_id is not None  # guaranteed by caller

    node = owner.to_node(project_root)
    file_path = node.md_path()
    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    anns = parse_annotations(text)
    open_ann = next(
        (a for a in anns if a.id == ann_id and not a.closing and not a.self_closing),
        None,
    )
    close_ann = next(
        (a for a in anns if a.id == ann_id and a.closing),
        None,
    )
    if open_ann is None or close_ann is None:
        raise LensException(
            f"claim [{owner.operator}:{ann_id}] not found after rollback — "
            "the repository may be in an inconsistent state"
        )

    before = lines[: open_ann.line_start - 1]
    original = lines[open_ann.line_end : close_ann.line_start - 1]
    after = lines[close_ann.line_end :]
    rebuilt = "\n".join(before) + "\n" + "\n".join(original) + "\n" + "\n".join(after)

    file_path.write_text(rebuilt, encoding="utf-8")
    storage.stage_all()
