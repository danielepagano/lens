"""Line-number-less text addressing and patch application.

Operators can address a span of lines in a document (narrative node body or
KB object body) without referring to line numbers by providing the full,
verbatim content of the start line (and optional end line), plus optional
context lines immediately before and/or after to make the match unique.
This avoids the fragility of line numbers in streaming/interactive editing.

Terminology
-----------

``LineSelector`` describes one end of a selection:

- ``target``  – the exact content of the line to match (minus the newline),
  or one of the sentinels :data:`START_ANCHOR` (``"@@@start"``) /
  :data:`END_ANCHOR` (``"@@@end"``) which represent the cursor position at
  the very beginning / very end of the document.
- ``before``  – ordered context lines that must appear immediately before
  the target line (the last element is the line directly above ``target``).
  May be empty. May contain :data:`START_ANCHOR` **only as the first
  element**, meaning "the document starts here".
- ``after``   – ordered context lines that must appear immediately after
  the target line (the first element is the line directly below
  ``target``). May contain :data:`END_ANCHOR` **only as the last element**,
  meaning "the document ends here".

A ``Selection`` is either a single ``LineSelector`` (which addresses that
one line) or a ``start`` + ``end`` pair (inclusive range). When ``start``
is a cursor sentinel (``@@@start``/``@@@end``) and ``end`` is absent, the
selection is a zero-width insertion point.  Giving both ``@@@start`` and
``@@@end`` as start/end targets represents the entire document (full
replace).

Resolution
----------

:func:`resolve_selection` locates the selection in the document.  It
returns a half-open Python slice ``(slice_start, slice_end)`` over the
document's logical line list — suitable for `lines[slice_start:slice_end]
= new_lines`-style replacement.  Failures raise :class:`SelectionError`
with a descriptive message covering the three common problems:

1. ``target`` not found at all
2. ``target`` not uniquely identified — caller must add more context
3. selection start resolves *after* selection end

Patching
--------

:func:`apply_patches` takes a sequence of ``(Selection, content)`` pairs
and applies them to a text buffer in order, re-resolving each selection
against the current state of the document.  Content is treated as a raw
text blob — it is split into logical lines with :meth:`str.splitlines`,
so a trailing newline in ``content`` is swallowed (consistent with how
most editors treat "replace this span with this text").  Pass an empty
``content`` for a pure deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from lens.core.exceptions import LensException

START_ANCHOR = "@@@start"
END_ANCHOR = "@@@end"


class SelectionError(LensException):
    """Raised when a selection cannot be resolved in a document."""


@dataclass(frozen=True)
class LineSelector:
    """One end of a :class:`Selection`.

    ``target`` is the verbatim content of the line we want to select,
    without its trailing newline.  The sentinels :data:`START_ANCHOR` and
    :data:`END_ANCHOR` may be used instead to denote the document-start
    or document-end cursor positions.

    ``before`` / ``after`` hold optional context lines used to
    disambiguate ``target`` when it appears more than once.  The elements
    are stored in document order: the last element of ``before`` is the
    line directly above ``target``; the first element of ``after`` is the
    line directly below.  :data:`START_ANCHOR` may appear only as the
    first element of ``before`` (meaning "document starts here");
    :data:`END_ANCHOR` may appear only as the last element of ``after``
    (meaning "document ends here").
    """

    target: str
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Any, *, role: str = "selector") -> LineSelector:
        """Parse a selector from a tool-call dict. Raises SelectionError on error."""
        if not isinstance(data, dict):
            raise SelectionError(f"{role}: expected object, got {type(data).__name__}")
        data_d = cast(dict[str, Any], data)
        if "target" not in data_d:
            raise SelectionError(f"{role}: missing required field 'target'")
        target_raw = data_d["target"]
        if not isinstance(target_raw, str):
            raise SelectionError(f"{role}: 'target' must be a string")
        empty_list: list[Any] = []
        before_raw = data_d.get("before") or empty_list
        after_raw = data_d.get("after") or empty_list
        if not isinstance(before_raw, list) or not all(
            isinstance(x, str) for x in cast(list[Any], before_raw)
        ):
            raise SelectionError(f"{role}: 'before' must be an array of strings")
        if not isinstance(after_raw, list) or not all(
            isinstance(x, str) for x in cast(list[Any], after_raw)
        ):
            raise SelectionError(f"{role}: 'after' must be an array of strings")
        return cls(
            target=target_raw,
            before=tuple(cast(list[str], before_raw)),
            after=tuple(cast(list[str], after_raw)),
        )


@dataclass(frozen=True)
class Selection:
    """A span in a document, addressed by line content rather than line number.

    ``start`` alone addresses a single line (or a cursor position, if the
    start target is a sentinel).  ``end`` extends the selection through
    the matched end line, inclusive.  ``start`` and ``end`` may
    independently use :data:`START_ANCHOR` / :data:`END_ANCHOR` sentinels
    for document-edge positions.
    """

    start: LineSelector
    end: LineSelector | None = None

    @classmethod
    def from_dict(cls, data: Any) -> Selection:
        """Parse a selection from a tool-call dict. Raises SelectionError on error."""
        if not isinstance(data, dict):
            raise SelectionError(
                f"selection: expected object, got {type(data).__name__}"
            )
        data_d = cast(dict[str, Any], data)
        if "start" not in data_d:
            raise SelectionError("selection: missing required field 'start'")
        start = LineSelector.from_dict(data_d["start"], role="start")
        end_raw = data_d.get("end")
        end = (
            LineSelector.from_dict(end_raw, role="end") if end_raw is not None else None
        )
        return cls(start=start, end=end)


@dataclass(frozen=True)
class Patch:
    """A single selection-and-replacement operation."""

    selection: Selection
    content: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> Patch:
        """Parse a patch from a tool-call dict. Raises SelectionError on error."""
        if not isinstance(data, dict):
            raise SelectionError(f"patch: expected object, got {type(data).__name__}")
        data_d = cast(dict[str, Any], data)
        selection = Selection.from_dict(data_d)
        content_raw = data_d.get("content", "")
        if not isinstance(content_raw, str):
            raise SelectionError("patch: 'content' must be a string")
        return cls(selection=selection, content=content_raw)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_lines(text: str) -> tuple[list[str], bool]:
    """Split *text* into logical lines.

    Returns ``(lines, had_trailing_newline)``.  Using :meth:`str.splitlines`
    means a single trailing newline is treated as a terminator, not as an
    extra empty line.  The original trailing-newline state is preserved
    separately so the text can be round-tripped byte-for-byte (save for
    any in-place patch).
    """
    if text == "":
        return [], False
    had_trailing = text.endswith(("\n", "\r\n", "\r"))
    return text.splitlines(), had_trailing


def _join_lines(lines: list[str], had_trailing: bool) -> str:
    """Inverse of :func:`_split_lines`."""
    if not lines:
        return "\n" if had_trailing else ""
    result = "\n".join(lines)
    if had_trailing:
        result += "\n"
    return result


def _validate_context(selector: LineSelector, role: str) -> tuple[list[str], list[str], bool, bool]:
    """Return (cleaned_before, cleaned_after, requires_start, requires_end).

    Strips out anchors from the context lists and validates anchor
    placement.  ``requires_start`` means the target must be at the
    document's start (i.e. any cleaned ``before`` aligns from index 0);
    ``requires_end`` means likewise for the document's end.
    """
    before = list(selector.before)
    after = list(selector.after)
    requires_start = False
    requires_end = False

    # START anchor in `before` must be the first element, and appear at most once.
    start_count = before.count(START_ANCHOR)
    if start_count > 1:
        raise SelectionError(
            f"{role}: '{START_ANCHOR}' may appear at most once in 'before'"
        )
    if start_count == 1:
        if before[0] != START_ANCHOR:
            raise SelectionError(
                f"{role}: '{START_ANCHOR}' must be the first element of 'before'"
            )
        requires_start = True
        before = before[1:]
    if END_ANCHOR in before:
        raise SelectionError(
            f"{role}: '{END_ANCHOR}' is not allowed in 'before' context"
        )

    # END anchor in `after` must be the last element, and appear at most once.
    end_count = after.count(END_ANCHOR)
    if end_count > 1:
        raise SelectionError(
            f"{role}: '{END_ANCHOR}' may appear at most once in 'after'"
        )
    if end_count == 1:
        if after[-1] != END_ANCHOR:
            raise SelectionError(
                f"{role}: '{END_ANCHOR}' must be the last element of 'after'"
            )
        requires_end = True
        after = after[:-1]
    if START_ANCHOR in after:
        raise SelectionError(
            f"{role}: '{START_ANCHOR}' is not allowed in 'after' context"
        )

    return before, after, requires_start, requires_end


def _find_matches(lines: list[str], selector: LineSelector, role: str) -> list[int]:
    """Return all 0-based line indices where the selector's target matches.

    Takes context lines into account.  Skips cursor sentinels — the
    caller is expected to short-circuit those.
    """
    target = selector.target
    if target == START_ANCHOR or target == END_ANCHOR:
        raise SelectionError(
            f"{role}: cursor sentinel {target!r} cannot be matched as a line target"
        )
    before, after, requires_start, requires_end = _validate_context(selector, role)
    n = len(lines)
    matches: list[int] = []
    for i, line in enumerate(lines):
        if line != target:
            continue
        # Before context: rooms needed above i.
        if len(before) > i:
            continue
        if before and lines[i - len(before) : i] != before:
            continue
        if requires_start and (i - len(before)) != 0:
            continue
        # After context: rooms needed below i.
        if len(after) > n - i - 1:
            continue
        if after and lines[i + 1 : i + 1 + len(after)] != after:
            continue
        if requires_end and (i + 1 + len(after)) != n:
            continue
        matches.append(i)
    return matches


@dataclass(frozen=True)
class _Endpoint:
    """Resolved endpoint: either a concrete line or a document-edge anchor."""
    kind: str  # "line" | "start" | "end"
    index: int  # 0-based line index; 0 for start, len(lines) for end


def _resolve_endpoint(
    lines: list[str], selector: LineSelector, role: str
) -> _Endpoint:
    if selector.target == START_ANCHOR:
        if selector.before or selector.after:
            raise SelectionError(
                f"{role}: '{START_ANCHOR}' cursor target cannot have 'before' or 'after' context"
            )
        return _Endpoint(kind="start", index=0)
    if selector.target == END_ANCHOR:
        if selector.before or selector.after:
            raise SelectionError(
                f"{role}: '{END_ANCHOR}' cursor target cannot have 'before' or 'after' context"
            )
        return _Endpoint(kind="end", index=len(lines))

    matches = _find_matches(lines, selector, role)
    if not matches:
        raise SelectionError(
            f"{role}: no match for target {selector.target!r}"
            + (
                f" with before={list(selector.before)!r} after={list(selector.after)!r}"
                if (selector.before or selector.after)
                else ""
            )
        )
    if len(matches) > 1:
        raise SelectionError(
            f"{role}: target {selector.target!r} is ambiguous — "
            f"matches {len(matches)} lines ({[m + 1 for m in matches]}); "
            f"add context lines (before/after) to uniquely identify the intended line"
        )
    return _Endpoint(kind="line", index=matches[0])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedSelection:
    """Result of resolving a :class:`Selection` against a document."""

    slice_start: int
    slice_end: int  # exclusive
    lines: tuple[str, ...]
    had_trailing_newline: bool

    @property
    def is_cursor(self) -> bool:
        """True if this selection is a zero-width insertion point."""
        return self.slice_start == self.slice_end


def resolve_selection(text: str, selection: Selection) -> ResolvedSelection:
    """Resolve *selection* into a concrete slice over the lines of *text*.

    Raises :class:`SelectionError` when the start target cannot be found,
    is ambiguous, or when ``start`` resolves after ``end``.
    """
    lines, had_trailing = _split_lines(text)
    n = len(lines)

    start_ep = _resolve_endpoint(lines, selection.start, role="start")

    if selection.end is None:
        if start_ep.kind == "line":
            slice_start = start_ep.index
            slice_end = start_ep.index + 1
        elif start_ep.kind == "start":
            slice_start = 0
            slice_end = 0
        else:  # "end"
            slice_start = n
            slice_end = n
    else:
        end_ep = _resolve_endpoint(lines, selection.end, role="end")
        if start_ep.kind == "line":
            slice_start = start_ep.index
        elif start_ep.kind == "start":
            slice_start = 0
        else:
            slice_start = n
        if end_ep.kind == "line":
            slice_end = end_ep.index + 1  # inclusive -> exclusive
        elif end_ep.kind == "start":
            slice_end = 0
        else:
            slice_end = n
        if slice_start > slice_end:
            raise SelectionError(
                "selection is out of order: start line resolves after end line"
            )

    return ResolvedSelection(
        slice_start=slice_start,
        slice_end=slice_end,
        lines=tuple(lines),
        had_trailing_newline=had_trailing,
    )


def apply_patch(text: str, patch: Patch) -> str:
    """Apply a single patch to *text* and return the resulting text.

    Raises :class:`SelectionError` if the selection does not resolve.
    """
    resolved = resolve_selection(text, patch.selection)
    lines = list(resolved.lines)
    new_lines = patch.content.splitlines() if patch.content else []
    lines[resolved.slice_start : resolved.slice_end] = new_lines
    return _join_lines(lines, resolved.had_trailing_newline)


def apply_patches(text: str, patches: list[Patch]) -> str:
    """Apply *patches* to *text* in order, returning the final text.

    Each patch re-resolves against the current (already-patched) state
    of the text.  On failure the exception's message is prefixed with
    the 1-based patch index so the caller can identify which patch in
    the batch failed.
    """
    current = text
    for index, patch in enumerate(patches, start=1):
        try:
            current = apply_patch(current, patch)
        except SelectionError as e:
            raise SelectionError(f"patch #{index}: {e}") from e
    return current


def parse_patches(data: Any) -> list[Patch]:
    """Parse a list of patches from a tool-call payload.

    Accepts ``None`` (returns ``[]``) or a list of dicts.  Each dict
    must have ``start`` (required), optional ``end``, and optional
    ``content`` (defaults to the empty string).  Raises
    :class:`SelectionError` on structural errors.
    """
    if data is None:
        return []
    if not isinstance(data, list):
        raise SelectionError(
            f"patches: expected an array, got {type(data).__name__}"
        )
    data_list = cast(list[Any], data)
    result: list[Patch] = []
    for i, item in enumerate(data_list, start=1):
        try:
            result.append(Patch.from_dict(item))
        except SelectionError as e:
            raise SelectionError(f"patch #{i}: {e}") from e
    return result
