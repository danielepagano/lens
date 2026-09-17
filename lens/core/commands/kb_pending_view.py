"""The pending proposals at the cursor, as data a client can render.

Once ``design`` stops emitting fenced ``kb`` blocks, the narrative no longer
*shows* what a session is proposing: the ``[kb-op …]: #`` blocks are comments,
and every renderer in the stack hides them on purpose.  That is the whole point
for the model, and it would be a regression for the person, who could previously
read the fences in the node and click a diff button beside each one.

This is the replacement, and it is strictly more than the fences gave:

- every op, with its line span in the node — so a client (or a person with an
  editor) can go and change or delete the exact block, which is all "editing a
  proposal" has ever needed to mean;
- per-op validation, because a stack can go stale under a direct edit and a
  patch whose anchor is gone must say so rather than vanish at ``--end``;
- per-object **base and proposed text**, which is the diff pair — correct for
  patches, tags and removals, not only for whole bodies.

Building the UI is not this module's job; having nowhere to get the data was.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from lens.core.kb_pending import KbOp, KbOpError, parse_kb_ops
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.project import get_active_narrative

OpStatus = Literal["ok", "error"]
ChangeKind = Literal["created", "updated", "removed"]


@dataclass(frozen=True)
class PendingOpView:
    """One proposal, and whether it still resolves."""

    index: int
    op: str
    id: str
    line_start: int
    line_end: int
    summary: str
    status: OpStatus = "ok"
    error: str = ""


@dataclass(frozen=True)
class PendingObjectView:
    """One object the session would change, with both sides of the diff."""

    id: str
    change: ChangeKind
    base: str | None
    proposed: str | None
    base_source: str | None


@dataclass
class PendingKbView:
    node: str = ""
    ops: list[PendingOpView] = field(default_factory=list[PendingOpView])
    objects: list[PendingObjectView] = field(
        default_factory=list[PendingObjectView]
    )
    errors: list[str] = field(default_factory=list[str])

    def is_empty(self) -> bool:
        return not self.ops


def _summarize(op: KbOp) -> str:
    if op.op == "add":
        lines = (op.body or "").count("\n") + 1 if op.body else 0
        return f"whole body, {lines} line{'' if lines == 1 else 's'}"
    if op.op == "patch":
        count = len(op.patches)
        first: dict[str, Any] = op.patches[0] if op.patches else {}
        start: Any = first.get("start")
        target: Any = cast(dict[str, Any], start).get("target") if isinstance(start, dict) else None
        anchor = f" at {target!r}" if isinstance(target, str) and target else ""
        return f"{count} patch{'' if count == 1 else 'es'}{anchor}"
    if op.op == "tag":
        parts: list[str] = []
        if op.tags:
            parts.append(" ".join(f"+{tag}" for tag in op.tags))
        if op.remove_tags:
            parts.append(" ".join(f"-{tag}" for tag in op.remove_tags))
        return " ".join(parts)
    if op.op == "remove":
        return "delete"
    if op.op == "applied":
        written = ", ".join((*op.ids, *op.removed))
        return f"written at close: {written}" if written else "written at close"
    return ""


def pending_kb_view(
    project_root: Path, node: NarrativeNode | None = None
) -> PendingKbView:
    """Everything proposed at *node* (the cursor by default), with its status.

    Reads the node directly rather than the store's cached layer for the op
    list, because the line spans are what makes a proposal editable and only the
    text has them.  The fold itself comes from the store, so this view and every
    other reader agree about what the proposals currently mean.
    """
    store = KnowledgeStore.for_project(project_root)
    narrative = get_active_narrative(project_root)
    if narrative is None or not narrative.exists():
        return PendingKbView()
    cursor = narrative.find_cursor()
    if node is None:
        node = cursor
    elif node.path_str() != cursor.path_str():
        # The fold is the cursor's, so an op list read from any other node
        # would be validated against the wrong stack and attributed the wrong
        # objects.  A closed session still holds its blocks; they are history
        # there, not proposals, and this view only speaks about proposals.
        return PendingKbView()
    try:
        text = node.md_path().read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return PendingKbView()

    ops = parse_kb_ops(text)
    if not ops:
        return PendingKbView(node=node.path_str())

    layer = store.pending_layer()
    by_index: dict[int, KbOpError] = {error.index: error for error in layer.errors}
    view = PendingKbView(node=node.path_str())
    for index, op in enumerate(ops, start=1):
        error = by_index.get(index)
        view.ops.append(
            PendingOpView(
                index=index,
                op=op.op,
                id=op.id,
                line_start=op.line_start,
                line_end=op.line_end,
                summary=_summarize(op),
                status="error" if error is not None else "ok",
                error=error.reason if error is not None else "",
            )
        )
    view.errors = [str(error) for error in layer.errors]

    base_store = KnowledgeStore.for_project(project_root, pending=False)
    for canonical_id in sorted(layer.touched_ids()):
        base_obj = base_store.get_objects([canonical_id]).get(canonical_id)
        base_source = base_store.describe_source(canonical_id)
        if canonical_id in layer.removed:
            change: ChangeKind = "removed"
            proposed = None
        elif base_obj is None:
            change = "created"
            proposed = layer.objects.get(canonical_id, "")
        else:
            change = "updated"
            proposed = layer.objects.get(canonical_id, base_obj.text)
        view.objects.append(
            PendingObjectView(
                id=canonical_id,
                change=change,
                base=base_obj.text if base_obj is not None else None,
                proposed=proposed,
                base_source=base_source.label if base_source is not None else None,
            )
        )
    return view


def pending_payload(view: PendingKbView) -> dict[str, Any]:
    """JSON shape for the node route, ``--json``, and anything else."""
    return {
        "node": view.node,
        "ops": [
            {
                "index": op.index,
                "op": op.op,
                "id": op.id,
                "line_start": op.line_start,
                "line_end": op.line_end,
                "summary": op.summary,
                "status": op.status,
                "error": op.error,
            }
            for op in view.ops
        ],
        "objects": [
            {
                "id": obj.id,
                "change": obj.change,
                "base": obj.base,
                "proposed": obj.proposed,
                "base_source": obj.base_source,
            }
            for obj in view.objects
        ],
        "errors": view.errors,
    }


def format_pending_lines(view: PendingKbView) -> list[str]:
    """Human-readable rendering for ``lens kb pending``."""
    if view.is_empty():
        return ["No pending KB proposals at the cursor."]
    lines = [f"{view.node}: {len(view.ops)} proposal(s), not written yet"]
    for op in view.ops:
        marker = "!" if op.status == "error" else " "
        target = f" {op.id}" if op.id else ""
        lines.append(f"{marker} {op.op}{target} (line {op.line_start}) — {op.summary}")
        if op.error:
            lines.append(f"    {op.error}")
    if view.objects:
        lines.append("")
        for obj in view.objects:
            base = f" over {obj.base_source}" if obj.base_source else ""
            lines.append(f"  {obj.change}: {obj.id}{base}")
    return lines
