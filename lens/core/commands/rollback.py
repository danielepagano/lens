from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lens.core.annotations import parse_annotations
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.core.exceptions import LensException

if TYPE_CHECKING:
    from lens.core.address import NarrativeAddress

@dataclass
class RollbackStatus:
    has_pending: bool
    owner: NarrativeAddress | None
    is_mutation: bool


@dataclass
class RollbackResult:
    """Result of a rollback operation. ``performed`` is True if changes were discarded."""
    performed: bool
    status: RollbackStatus


def rollback(session: ProjectSession) -> RollbackResult:
    """Check for a pending transaction and, if present, discard it.

    Returns a result with ``performed=True`` when a rollback was executed,
    ``performed=False`` when there was nothing to roll back.
    """
    status = check_rollback_status(session)
    if not status.has_pending:
        return RollbackResult(performed=False, status=status)
    execute_rollback(session)
    return RollbackResult(performed=True, status=status)


def check_rollback_status(session: ProjectSession) -> RollbackStatus:
    storage = session.new_storage()
    has_pending = storage.has_pending()
    owner = storage.detect_pending_owner() if has_pending else None
    is_mutation = owner is not None and owner.operator == "edit"

    # Also check for staged mutation claims (edit cancelled before proposal)
    if owner is None and storage.has_staged():
        staged_owner = storage.detect_staged_owner()
        if staged_owner is not None and staged_owner.operator == "edit":
            return RollbackStatus(
                has_pending=True, owner=staged_owner, is_mutation=True
            )

    return RollbackStatus(has_pending, owner, is_mutation)

def execute_rollback(session: ProjectSession) -> None:
    storage = session.new_storage()
    owner = storage.detect_pending_owner()
    is_mutation = owner is not None and owner.operator == "edit"

    if is_mutation:
        assert owner is not None
        compensating_rollback(storage, owner, session.project_root)
    elif owner is not None:
        # Non-mutation operator with unstaged changes
        storage.rollback()
    else:
        # No unstaged owner found - check for staged mutation claims.
        # This happens when edit is cancelled before propose_mutation() is called:
        # the claim tags are staged but there are no unstaged changes yet.
        staged_owner = storage.detect_staged_owner()
        if staged_owner is not None and staged_owner.operator == "edit":
            # Unstage the claim tags, then discard them from working tree.
            # This restores the file to its original state (HEAD).
            storage.unstage_all()
            storage.rollback()
        else:
            # No pending transaction - just ensure working tree is clean
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
    # Body between the open and close tags contains the original claimed lines,
    # plus one synthetic blank line inserted by start_mutation right before the
    # closing tag. Drop a single trailing empty line if present to recover the
    # original range exactly.
    body = lines[open_ann.line_end : close_ann.line_start - 1]
    if body and body[-1] == "":
        body = body[:-1]
    after = lines[close_ann.line_end :]
    rebuilt_lines = before + body + after
    rebuilt = "\n".join(rebuilt_lines)
    file_path.write_text(rebuilt, encoding="utf-8")
    storage.stage_all()
