"""Turn-based passage parsing for multi-turn LLM context assembly.

Classifies each LLM-visible line in a node as a user or assistant turn based
on annotation boundaries:

- Content inside ``[op]...[/op]`` pairs with **no id** → ``assistant``
  (regular operator output; fair game for the model to revise).
- Content inside ``[op:id]...[/op:id]`` pairs **with an id** → ``user``
  (summary nodes — section, advance, etc.; must not be broken or rewritten).
- Content **outside** all annotation pairs → ``user``
  (player lines, character dialogue, manual edits).

Consecutive lines with the same role are merged into one turn; whitespace-only
turns are dropped.  Returns an empty list when no closed annotation pairs are
found — callers fall back to single-turn assembly.

The function works from a :class:`~lens.core.storage_text.NormalizedStorageText`
instance so the caller reuses the cached normalization already populated by
:func:`~lens.core.context.crawl` via the same ``Storage`` instance.
``parse_annotations`` runs once on the raw storage text: one cheap text scan,
not separately cached.

Line number conventions
-----------------------
``ParsedAnnotation.line_start`` is **1-based** (the 1-based line number of the
first line of the annotation header).  ``ParsedAnnotation.line_end`` is the
**0-based** index of the first line *after* the annotation block (matching how
``text.split("\\n")[open.line_end : ...]`` is used in ``extract_annotation_content``).

Therefore, content between an open/close pair occupies 1-based disk lines
``open.line_end + 1`` to ``close.line_start - 1`` inclusive.
"""

from __future__ import annotations

from lens.core.annotations import ParsedAnnotation, parse_annotations
from lens.core.mount_embed_strip import line_is_standalone_lens_mount_attachment
from lens.core.storage_text import NormalizedStorageText


def _build_annotation_intervals(
    anns: list[ParsedAnnotation],
) -> list[tuple[int, int, str]]:
    """Return ``(content_start_1based, content_end_1based, role)`` for each closed pair.

    *role* is ``"assistant"`` for pairs with no id, ``"user"`` for pairs with an id
    (summary operators such as ``section`` and ``advance``).

    Content occupies 1-based disk lines ``open.line_end + 1`` to
    ``close.line_start - 1`` (see module docstring for the reasoning).

    Pairs with an empty content range (``start > end``) are skipped.
    Nesting is handled with a stack; intervals are appended in close order
    (innermost pairs first).
    """
    open_stack: list[ParsedAnnotation] = []
    intervals: list[tuple[int, int, str]] = []
    for ann in anns:
        if ann.self_closing:
            continue
        if not ann.closing:
            open_stack.append(ann)
        else:
            for i in range(len(open_stack) - 1, -1, -1):
                if open_stack[i].operator == ann.operator and open_stack[i].id == ann.id:
                    opening = open_stack.pop(i)
                    content_start = opening.line_end + 1
                    content_end = ann.line_start - 1
                    if content_start <= content_end:
                        role = "user" if opening.id is not None else "assistant"
                        intervals.append((content_start, content_end, role))
                    break
    return intervals


def _role_for_disk_line(disk_line: int, intervals: list[tuple[int, int, str]]) -> str:
    """Return the role for a 1-based disk line number.

    Scans *intervals* in order (innermost first due to stack pop order) and
    returns the first match.  Defaults to ``"user"`` when no interval matches.
    """
    for start, end, role in intervals:
        if start <= disk_line <= end:
            return role
    return "user"


def _group_turns(line_roles: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Group consecutive same-role lines into ``(role, content)`` turns.

    Strips each turn's content and drops turns that are empty after stripping.
    """
    if not line_roles:
        return []
    turns: list[tuple[str, str]] = []
    current_role = line_roles[0][1]
    current_lines: list[str] = [line_roles[0][0]]
    for line, role in line_roles[1:]:
        if role == current_role:
            current_lines.append(line)
        else:
            content = "\n".join(current_lines).strip()
            if content:
                turns.append((current_role, content))
            current_role = role
            current_lines = [line]
    content = "\n".join(current_lines).strip()
    if content:
        turns.append((current_role, content))
    return turns


def parse_passage_turns(
    normalized: NormalizedStorageText,
) -> list[tuple[str, str]]:
    """Parse a node's LLM-visible text into ``(role, content)`` turns.

    Returns an empty list when no closed annotation pairs are found — the
    caller should fall back to single-turn prompt assembly in that case.

    Call with the :class:`~lens.core.storage_text.NormalizedStorageText` for the
    current node, obtained via
    :meth:`~lens.core.storage.Storage.normalize_path_text`.  When
    :func:`~lens.core.context.crawl` was called with the same ``Storage``
    instance, this is a cache hit with zero disk I/O.
    """
    anns = parse_annotations(normalized.raw_storage_text)
    intervals = _build_annotation_intervals(anns)
    if not intervals:
        return []

    llm_view = normalized.llm_view
    if not llm_view.visible_for_llm.strip():
        return []

    visible_lines = llm_view.visible_for_llm.splitlines()
    disk_starts = llm_view.disk_line_start_1based

    line_roles: list[tuple[str, str]] = [
        (line, _role_for_disk_line(disk, intervals))
        for line, disk in zip(visible_lines, disk_starts)
        if not line_is_standalone_lens_mount_attachment(line)
    ]
    return _group_turns(line_roles)
