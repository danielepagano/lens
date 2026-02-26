"""Discard the pending transaction (unstaged changes and untracked files).

For **inline** operators (e.g. write): simple discard of unstaged changes.

For **mutation** operators (e.g. edit): a compensating transaction is applied
instead.  The proposal (unstaged) is dropped and the staged claim tags are
removed, leaving the original text intact and staged.  This matches the design
principle that a mutation rollback should leave no trace of the operator while
restoring the content that was being edited.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from lens.annotations import parse_annotations
from lens.project import require_lens_context
from lens.storage import Storage

if TYPE_CHECKING:
    from lens.address import NarrativeAddress

app = typer.Typer(invoke_without_command=True)


def compensating_rollback(
    storage: Storage,
    owner: NarrativeAddress,
    project_root: Path,
) -> None:
    """Apply the compensating transaction for a pending mutation proposal.

    Restores the working tree to the staged claim state, then removes the
    claim tags and re-stages, leaving the original selected text intact.
    """
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
        raise RuntimeError(
            f"claim [{owner.operator}:{ann_id}] not found after rollback — "
            "the repository may be in an inconsistent state"
        )

    before = lines[: open_ann.line_start - 1]
    original = lines[open_ann.line_end : close_ann.line_start - 1]
    after = lines[close_ann.line_end :]
    rebuilt = "\n".join(before) + "\n" + "\n".join(original) + "\n" + "\n".join(after)

    file_path.write_text(rebuilt, encoding="utf-8")
    storage.stage_all()


@app.callback()
def rollback(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt.",
    ),
) -> None:
    """Discard the pending transaction, reverting all unstaged changes."""
    try:
        git_root, project_root = require_lens_context(Path.cwd())
    except RuntimeError as e:
        typer.echo(f"lens rollback: {e}", err=True)
        raise typer.Exit(1)

    storage = Storage(git_root)
    if not storage.has_pending():
        typer.echo("No pending transaction to roll back.")
        raise typer.Exit(0)

    owner = storage.detect_pending_owner()
    is_mutation = owner is not None and owner.op_id is not None

    if owner is not None:
        typer.echo(f"Pending transaction owner: {owner}")
    else:
        typer.echo("Pending transaction owner: (non-operator changes)")

    if is_mutation:
        typer.echo(
            "Mutation operator detected — rollback will apply a compensating "
            "transaction (claim tags removed, original text restored)."
        )

    if not yes:
        typer.confirm("Roll back?", abort=True)

    try:
        if is_mutation:
            assert owner is not None
            compensating_rollback(storage, owner, project_root)
            typer.echo("Compensating transaction applied.")
        else:
            storage.rollback()
            typer.echo("Transaction rolled back.")
    except Exception as e:
        typer.echo(f"lens rollback: {e}", err=True)
        raise typer.Exit(1)
