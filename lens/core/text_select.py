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
- ``before``  – ordered **full** adjacent lines (verbatim, same rules as
  ``target`` — never a substring of a line). The last element is the line
  directly above ``target``. May be empty. May contain :data:`START_ANCHOR`
  **only as the first element**, meaning "the document starts here".
- ``after``   – ordered **full** adjacent lines below ``target`` (first
  element is directly under ``target``). May contain :data:`END_ANCHOR`
  **only as the last element**, meaning "the document ends here".

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
= new_lines`-style replacement.  The **contract** for tool callers is:
``target`` is the exact full logical line (or a cursor sentinel);
``before``/``after`` are optional full adjacent lines to disambiguate
repeated lines.  The resolver still applies exact-line matching first, then
a narrow resilience path (globally unique single substring occurrence,
no ``\\n`` in ``target``), then contextual full-line matching — callers
should follow the strict contract and not rely on the resilience path.
Failures raise :class:`SelectionError` with a descriptive message covering
the common problems:

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
from typing import TYPE_CHECKING, Any, cast

from lens.core.exceptions import LensException
from lens.core.storage_text import (
    StorageLlmView,
    StorageNormalizationError,
    normalize_storage_text,
)

START_ANCHOR = "@@@start"
END_ANCHOR = "@@@end"

if TYPE_CHECKING:
    from lens.core.storage import Storage


class SelectionError(LensException):
    """Raised when a selection cannot be resolved in a document."""


@dataclass(frozen=True)
class LineSelector:
    """One end of a :class:`Selection`.

    ``target`` is the verbatim full line to select (no trailing newline),
    or the sentinels :data:`START_ANCHOR` / :data:`END_ANCHOR` for document
    edges.

    ``before`` / ``after`` hold optional **whole-line** context (verbatim
    full lines, never fragments) used to disambiguate ``target`` when it
    appears more than once.  The elements are stored in document order: the
    last element of ``before`` is the line directly above ``target``; the
    first element of ``after`` is the line directly below.  :data:`START_ANCHOR` may appear only as the
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


def _normalize_line_for_match(line: str) -> str:
    """Normalize a storage line for anchor matching (trailing whitespace only)."""
    return line.rstrip()


def _lines_match_for_selection(line: str, target: str) -> bool:
    return _normalize_line_for_match(line) == _normalize_line_for_match(target)


def _sanitize_selector_context(selector: LineSelector) -> LineSelector:
    """Drop mistaken context where ``before`` repeats ``target`` (common LLM error)."""
    before = list(selector.before)
    while before and _lines_match_for_selection(before[-1], selector.target):
        before.pop()
    after = list(selector.after)
    while after and _lines_match_for_selection(after[0], selector.target):
        after.pop(0)
    if before == list(selector.before) and after == list(selector.after):
        return selector
    return LineSelector(target=selector.target, before=tuple(before), after=tuple(after))


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
    selector = _sanitize_selector_context(selector)
    target = selector.target
    if target == START_ANCHOR or target == END_ANCHOR:
        raise SelectionError(
            f"{role}: cursor sentinel {target!r} cannot be matched as a line target"
        )
    before, after, requires_start, requires_end = _validate_context(selector, role)
    n = len(lines)
    matches: list[int] = []
    for i, line in enumerate(lines):
        if not _lines_match_for_selection(line, target):
            continue
        # Before context: rooms needed above i.
        if len(before) > i:
            continue
        if before and not all(
            _lines_match_for_selection(lines[i - len(before) + j], before[j])
            for j in range(len(before))
        ):
            continue
        if requires_start and (i - len(before)) != 0:
            continue
        # After context: rooms needed below i.
        if len(after) > n - i - 1:
            continue
        if after and not all(
            _lines_match_for_selection(lines[i + 1 + j], after[j])
            for j in range(len(after))
        ):
            continue
        if requires_end and (i + 1 + len(after)) != n:
            continue
        matches.append(i)
    return matches


def _substring_unique_occurrence_line_index(lines: list[str], target: str) -> int | None:
    """If *target* occurs exactly once in the whole document as a substring (no ``\\n`` in *target*), return that line index; else ``None``."""
    if not target or "\n" in target:
        return None
    norm_target = _normalize_line_for_match(target)
    total = 0
    last_i: int | None = None
    for i, ln in enumerate(lines):
        norm_ln = _normalize_line_for_match(ln)
        if norm_target in norm_ln:
            total += norm_ln.count(norm_target)
            if total > 1:
                return None
            last_i = i
    return last_i if total == 1 else None


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

    selector = _sanitize_selector_context(selector)
    target = selector.target
    _validate_context(selector, role)
    has_ctx = bool(selector.before or selector.after)
    solo_sel = LineSelector(target=target, before=(), after=())
    solo_matches = _find_matches(lines, solo_sel, role)

    if len(solo_matches) == 1:
        return _Endpoint(kind="line", index=solo_matches[0])

    if len(solo_matches) == 0:
        sub_i = _substring_unique_occurrence_line_index(lines, target)
        if sub_i is not None:
            return _Endpoint(kind="line", index=sub_i)
        if has_ctx:
            ctx_matches = _find_matches(lines, selector, role)
            if len(ctx_matches) == 1:
                return _Endpoint(kind="line", index=ctx_matches[0])
            if not ctx_matches:
                raise SelectionError(
                    f"{role}: no match for target {target!r}"
                    f" with before={list(selector.before)!r} after={list(selector.after)!r}"
                )
            raise SelectionError(
                f"{role}: target {target!r} is ambiguous — "
                f"matches {len(ctx_matches)} lines ({[m + 1 for m in ctx_matches]}); "
                "tighten before/after context"
            )
        raise SelectionError(f"{role}: no match for target {target!r}")

    if not has_ctx:
        raise SelectionError(
            f"{role}: target {target!r} is ambiguous — "
            f"matches {len(solo_matches)} lines ({[m + 1 for m in solo_matches]}); "
            "add context lines (before/after) to uniquely identify the intended line"
        )
    ctx_matches = _find_matches(lines, selector, role)
    if len(ctx_matches) == 1:
        return _Endpoint(kind="line", index=ctx_matches[0])
    if not ctx_matches:
        raise SelectionError(
            f"{role}: no match for target {target!r}"
            f" with before={list(selector.before)!r} after={list(selector.after)!r}"
        )
    raise SelectionError(
        f"{role}: target {target!r} is ambiguous — "
        f"matches {len(ctx_matches)} lines ({[m + 1 for m in ctx_matches]}); "
        "tighten before/after context"
    )


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


def storage_text_llm_view(raw_storage_text: str) -> StorageLlmView:
    """Strip markdown comments like crawl, then ``decode_ai_secrets`` (assemble parity)."""
    try:
        return normalize_storage_text(raw_storage_text).llm_view
    except StorageNormalizationError as e:
        raise SelectionError(str(e)) from e


def resolve_storage_selection_to_disk_inclusive_lines_via_llm_view(
    raw_storage_text: str, selection: Selection
) -> tuple[int, int]:
    """Resolve *selection* on the LLM-visible storage buffer; return 1-based inclusive disk lines."""
    view = storage_text_llm_view(raw_storage_text)
    if not view.visible_for_llm.strip():
        raise SelectionError("storage text has no visible lines after stripping comments")
    resolved = resolve_selection(view.visible_for_llm, selection)
    if resolved.is_cursor:
        raise SelectionError("selection resolved to an empty range (use cursor splice helpers)")
    n = len(view.disk_line_start_1based)
    if resolved.slice_end <= resolved.slice_start or resolved.slice_start >= n:
        raise SelectionError("resolved selection is out of range for storage view")
    last = resolved.slice_end - 1
    start_disk = view.disk_line_start_1based[resolved.slice_start]
    end_disk = view.disk_line_end_1based[last]
    return start_disk, end_disk


def _splice_insert_before_disk_line(
    raw_storage_text: str, before_disk_1: int, replacement_lines: list[str]
) -> str:
    """Insert *replacement_lines* immediately before physical line ``before_disk_1`` (1-based)."""
    lines = raw_storage_text.split("\n")
    a = before_disk_1 - 1
    if a < 0 or a > len(lines):
        raise SelectionError(
            f"insert-before line {before_disk_1} is out of bounds (file has {len(lines)} lines)"
        )
    return "\n".join(lines[:a] + replacement_lines + lines[a:])


def splice_storage_text_by_inclusive_disk_lines(
    raw_storage_text: str,
    start_disk_1: int,
    end_disk_1_inclusive: int,
    replacement_lines: list[str],
) -> str:
    """Replace inclusive disk line range ``start_disk_1``..``end_disk_1_inclusive`` with *replacement_lines*."""
    lines = raw_storage_text.split("\n")
    a = start_disk_1 - 1
    b = end_disk_1_inclusive
    if a < 0 or b > len(lines) or a > b:
        raise SelectionError(
            f"disk line range {start_disk_1}–{end_disk_1_inclusive} is out of bounds "
            f"(file has {len(lines)} lines)"
        )
    before = lines[:a]
    after = lines[b:]
    return "\n".join(before + replacement_lines + after)


def _llm_view_for_storage_text(
    raw_storage_text: str,
    *,
    storage: Storage | None = None,
    source_id: str | None = None,
) -> StorageLlmView:
    if storage is None:
        return storage_text_llm_view(raw_storage_text)
    return storage.normalize_raw_text(
        raw_storage_text, source_id=source_id
    ).llm_view


def _patch_bullets_already_in_llm_view(view: StorageLlmView, content: str) -> bool:
    """True when every bullet line in *content* already appears in the visible body."""
    bullets = [
        ln
        for ln in content.splitlines()
        if ln.strip().startswith("-")
    ]
    if not bullets:
        return False
    norm_visible = {
        _normalize_line_for_match(ln) for ln in view.visible_for_llm.splitlines()
    }
    return all(_normalize_line_for_match(b) in norm_visible for b in bullets)


def patch_content_already_present_in_llm_view(
    raw_storage_text: str,
    patch: Patch,
    *,
    storage: Storage | None = None,
    source_id: str | None = None,
) -> bool:
    content = patch.content.strip()
    if not content:
        return False
    view = _llm_view_for_storage_text(
        raw_storage_text, storage=storage, source_id=source_id
    )
    if content in view.visible_for_llm:
        return True
    return _patch_bullets_already_in_llm_view(view, content)


def _patch_is_cursor_insert_only(patch: Patch) -> bool:
    if patch.selection.end is not None:
        return False
    return patch.selection.start.target in (START_ANCHOR, END_ANCHOR)


def patches_effect_already_present_in_storage_text(
    raw_storage_text: str,
    patches: list[Patch],
    *,
    storage: Storage | None = None,
    source_id: str | None = None,
    insert_only: bool = False,
) -> bool:
    if not patches:
        return False
    for patch in patches:
        if insert_only and not _patch_is_cursor_insert_only(patch):
            return False
        if not patch.content.strip():
            return False
        if not patch_content_already_present_in_llm_view(
            raw_storage_text,
            patch,
            storage=storage,
            source_id=source_id,
        ):
            return False
    return True


def apply_patches_to_storage_text_via_llm_view(
    raw_storage_text: str,
    patches: list[Patch],
    *,
    storage: Storage | None = None,
    source_id: str | None = None,
) -> str:
    """Like :func:`apply_patches` but resolve each patch on the LLM-visible buffer."""
    current = raw_storage_text
    for index, patch in enumerate(patches, start=1):
        try:
            if storage is None:
                view = storage_text_llm_view(current)
            else:
                view = storage.normalize_raw_text(
                    current, source_id=source_id
                ).llm_view
            if not view.visible_for_llm.strip():
                raise SelectionError("storage text has no visible lines after stripping comments")
            resolved = resolve_selection(view.visible_for_llm, patch.selection)
            new_lines = patch.content.splitlines() if patch.content else []
            n = len(view.disk_line_start_1based)
            if resolved.is_cursor:
                if resolved.slice_start == 0 and resolved.slice_end == 0:
                    before_1 = view.disk_line_start_1based[0] if n else 1
                    current = _splice_insert_before_disk_line(current, before_1, new_lines)
                elif resolved.slice_start == n and resolved.slice_end == n and n > 0:
                    after_last = view.disk_line_end_1based[n - 1]
                    current = _splice_insert_before_disk_line(
                        current, after_last + 1, new_lines
                    )
                else:
                    raise SelectionError(
                        "unsupported zero-width selection for storage patch "
                        f"(slice {resolved.slice_start}:{resolved.slice_end}, n={n})"
                    )
            else:
                if resolved.slice_end <= resolved.slice_start or resolved.slice_start >= n:
                    raise SelectionError("resolved selection is out of range for storage view")
                last = resolved.slice_end - 1
                start_disk = view.disk_line_start_1based[resolved.slice_start]
                end_disk = view.disk_line_end_1based[last]
                current = splice_storage_text_by_inclusive_disk_lines(
                    current, start_disk, end_disk, new_lines
                )
        except SelectionError as e:
            raise SelectionError(f"patch #{index}: {e}") from e
    return current


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
