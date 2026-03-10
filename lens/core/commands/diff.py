"""Diff parsing for surfacing transaction and staged state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from lens.core.annotations import ANNOTATION_OPEN_RE, ANNOTATION_RE
from lens.core.storage import Storage

_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# Matches the closing `]: #` line of a multi-line annotation block.
_ANNOTATION_END_RE = re.compile(r"^\s*\]:\s*#\s*$")


@dataclass
class DiffLine:
    kind: Literal["add", "remove"]
    text: str
    is_annotation: bool


@dataclass
class DiffHunk:
    old_start: int
    new_start: int
    lines: list[DiffLine] = field(default_factory=list[DiffLine])


@dataclass
class FileDiff:
    path: str
    hunks: list[DiffHunk] = field(default_factory=list[DiffHunk])


@dataclass
class TransactionState:
    has_pending: bool
    owner: str | None
    is_mutation: bool
    files: list[FileDiff]


def _classify_annotation(text: str, in_annotation: bool) -> tuple[bool, bool]:
    """Return (is_annotation, new_in_annotation) for a single diff content line.

    Handles single-line annotations, multi-line annotation openers (state
    transitions to True), YAML param lines inside a block, and closing `]: #`
    lines (state transitions to False).  An orphaned `]: #` (closing tag whose
    opener preceded the current hunk) is always marked as an annotation.
    """
    stripped = text.strip()
    if ANNOTATION_RE.match(stripped):
        # Single-line `[op:id]: #` — always an annotation, closes any open block.
        return True, False
    if _ANNOTATION_END_RE.match(stripped):
        # Orphaned or in-block `]: #` — always annotation, always closes block.
        return True, False
    if in_annotation:
        # Inside a multi-line block: YAML param lines belong to the annotation.
        return True, True
    if ANNOTATION_OPEN_RE.match(stripped):
        # Multi-line opener `[op:id` without `]: #` — opens a block.
        return True, True
    return False, False


def parse_unified_diff(text: str) -> list[FileDiff]:
    """Parse unified diff text into structured FileDiff objects.

    Only ``add`` and ``remove`` lines are included — context lines are dropped.
    Each hunk carries ``old_start`` / ``new_start`` line numbers so the UI can
    locate changes without needing surrounding context text.

    Multi-line annotation blocks (``[op\\n  params\\n]: #``) are detected via a
    stateful parser; ``is_annotation`` is set correctly for opener, param, and
    closing lines.
    """
    if not text.strip():
        return []

    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: DiffHunk | None = None

    # Track annotation-block state separately for the remove side and add side.
    # State persists across hunks within a file (blocks can straddle hunk
    # boundaries) but resets on each new file.
    in_remove_annotation = False
    in_add_annotation = False

    for raw in text.splitlines():
        # New file section — reset per-file annotation state.
        m = _DIFF_FILE_RE.match(raw)
        if m:
            current_file = FileDiff(path=m.group(1))
            files.append(current_file)
            current_hunk = None
            in_remove_annotation = False
            in_add_annotation = False
            continue

        if (
            raw.startswith("--- ")
            or raw.startswith("diff ")
            or raw.startswith("index ")
            or raw.startswith("new file")
            or raw.startswith("deleted file")
            or raw.startswith("old mode")
            or raw.startswith("new mode")
        ):
            continue

        if current_file is None:
            continue

        hm = _HUNK_HEADER_RE.match(raw)
        if hm:
            current_hunk = DiffHunk(old_start=int(hm.group(1)), new_start=int(hm.group(2)))
            current_file.hunks.append(current_hunk)
            continue

        if current_hunk is None:
            continue

        if raw.startswith("\\"):
            # "\ No newline at end of file" — skip
            continue

        if raw.startswith("+") and not raw.startswith("+++"):
            content = raw[1:]
            is_ann, in_add_annotation = _classify_annotation(content, in_add_annotation)
            current_hunk.lines.append(DiffLine(kind="add", text=content, is_annotation=is_ann))
        elif raw.startswith("-") and not raw.startswith("---"):
            content = raw[1:]
            is_ann, in_remove_annotation = _classify_annotation(content, in_remove_annotation)
            current_hunk.lines.append(DiffLine(kind="remove", text=content, is_annotation=is_ann))
        # Context lines are skipped — line numbers on the hunk are sufficient.

    return files


def get_transaction_state(storage: Storage) -> TransactionState:
    """Return the current pending (unstaged) transaction state."""
    has_pending = storage.has_pending()
    if not has_pending:
        return TransactionState(has_pending=False, owner=None, is_mutation=False, files=[])

    raw_diff = storage.pending_diff()
    files = parse_unified_diff(raw_diff)
    owner_addr = storage.detect_pending_owner()
    owner_str = str(owner_addr) if owner_addr is not None else None
    is_mutation = owner_addr is not None and owner_addr.operator == "edit"

    return TransactionState(
        has_pending=True,
        owner=owner_str,
        is_mutation=is_mutation,
        files=files,
    )


def get_staged_state(storage: Storage) -> TransactionState:
    """Return the current staged (pending checkpoint) state."""
    raw_diff = storage.staged_diff()
    if not raw_diff.strip():
        return TransactionState(has_pending=False, owner=None, is_mutation=False, files=[])

    files = parse_unified_diff(raw_diff)
    from lens.core.storage import detect_pending_owner_from_diff

    owner_addr = detect_pending_owner_from_diff(raw_diff)
    owner_str = str(owner_addr) if owner_addr is not None else None
    is_mutation = owner_addr is not None and owner_addr.operator == "edit"

    return TransactionState(
        has_pending=True,
        owner=owner_str,
        is_mutation=is_mutation,
        files=files,
    )
