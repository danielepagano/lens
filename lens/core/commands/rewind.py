"""Core implementation of the ``lens rewind`` command.

Rewind puts the cursor at a given node or line by deleting everything after
that point in the narrative tree.

Node-level rewind (no line number)
------------------------------------
``rewind_to_node(target, storage)`` makes *target* the active cursor:

1. For each ancestor from *target* up to the root: if the parent file has
   content after *target*'s opening annotation (summary, close tag, later
   siblings), truncate the parent file at the opening annotation and delete
   the orphaned child nodes.  Stop as soon as a level is already open (all
   higher levels are transitively open too).
2. Remove any unclosed ``[section:…]: #`` annotation at the tail of
   *target*'s own file and delete the corresponding child node.

Line-level rewind
-----------------
``rewind_to_line(target, line, storage)`` truncates *target*'s file at
*line* (1-based) with structural adjustments:

* Line in **front matter** → clear the node entirely (empty file).
* Line **within a multi-line annotation tag** → delete the whole annotation
  and everything after it.
* Line in the **body of a section block** → delete the entire section block
  (open tag + summary/body + close tag) plus its child node, because a
  section cannot be left open without a child node and we cannot retain a
  partial summary.
* Line in the **body of a write / edit / other block** → truncate the body
  at *line* and re-close the tag (write always produces a closed block).
* Otherwise (free text) → simple truncation.

In all cases, child nodes whose section opening annotations are no longer
present in the file after the cut are deleted from disk.

Side effects (e.g. KB objects created by ``design``) are never touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lens.core.annotations import ParsedAnnotation, find_front_matter_span, parse_annotations
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation, parse_segments
from lens.core.storage import Storage

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rewind_to_node(target: NarrativeNode, storage: Storage) -> None:
    """Make *target* the cursor by opening the path to it and cleaning its tail.

    Raises ``LensException`` if the node does not exist or its opening
    annotation cannot be found in the parent.
    """
    if not target.exists():
        raise LensException(f"Node '{target.path_str()}' does not exist")

    key_path = target.key_path

    # Walk from target's depth back toward the root, ensuring each section is
    # open (unclosed) in its parent.
    for depth in range(len(key_path), 0, -1):
        current_key = key_path[depth - 1]
        parent = NarrativeNode(
            narrative_root=target.narrative_root,
            key_path=key_path[: depth - 1],
        )

        parent_text = parent.md_path().read_text(encoding="utf-8")
        parent_anns = parse_annotations(parent_text)

        current_open_ann = next(
            (
                a
                for a in parent_anns
                if a.operator == "section"
                and a.id == current_key
                and not a.closing
                and not a.self_closing
            ),
            None,
        )

        if current_open_ann is None:
            raise LensException(
                f"No [section:{current_key}] annotation found in "
                f"'{parent.path_str()}'"
            )

        # If nothing follows target's opening annotation in the parent file,
        # the section is already open here.  All higher ancestors are
        # transitively open too, so we can stop.
        has_content_after = any(
            a.line_start > current_open_ann.line_end for a in parent_anns
        )
        if not has_content_after:
            break

        # Truncate the parent file right after the opening annotation.
        parent_lines = parent_text.split("\n")
        new_lines = parent_lines[: current_open_ann.line_end]
        while new_lines and not new_lines[-1].strip():
            new_lines.pop()
        storage.write_file(parent.md_path(), "\n".join(new_lines) + "\n")

        # Delete all child nodes whose section opening annotations are now gone.
        for ann in parent_anns:
            if (
                ann.line_start > current_open_ann.line_end
                and ann.operator == "section"
                and not ann.closing
                and not ann.self_closing
                and ann.id is not None
            ):
                _delete_node(parent.child_node(ann.id), storage)

    # Remove any unclosed section annotation at the tail of the target's file
    # so that find_cursor() lands exactly on *target*.
    _clean_node_tail(target, storage)


def rewind_to_line(target: NarrativeNode, line: int, storage: Storage) -> None:
    """Truncate *target*'s file at *line* (1-based) with structural adjustments.

    Raises ``LensException`` if the node does not exist or *line* is out of
    range.
    """
    if not target.exists():
        raise LensException(f"Node '{target.path_str()}' does not exist")

    node_text = target.md_path().read_text(encoding="utf-8")
    node_lines = node_text.split("\n")
    total_lines = len(node_lines)

    if line < 1 or line > total_lines:
        raise LensException(
            f"Line {line} is out of range for '{target.path_str()}' "
            f"(1\u2013{total_lines})"
        )

    all_anns = parse_annotations(node_text)

    # --- Front matter ---------------------------------------------------------
    fm_span = find_front_matter_span(node_text)
    if fm_span is not None:
        # find_front_matter_span returns (start_0based, end_exclusive_0based).
        # Converting: first_1based = start_0 + 1, last_1based = end_0.
        fm_first = fm_span[0] + 1
        fm_last = fm_span[1]
        if fm_first <= line <= fm_last:
            # Rewind into front matter → clear the node entirely.
            _apply_cut(target, node_lines, 0, all_anns, storage)
            return

    # --- Line within an annotation tag ----------------------------------------
    for ann in all_anns:
        if ann.line_start <= line <= ann.line_end:
            if ann.closing:
                # Line is on or within a closing tag: keep it (truncate after).
                _apply_cut(target, node_lines, ann.line_end, all_anns, storage)
            else:
                # Line is within an opening annotation tag: delete it and everything after.
                _apply_cut(
                    target, node_lines, ann.line_start - 1, all_anns, storage
                )
            return

    # --- Line within an annotation body ---------------------------------------
    segments = parse_segments(node_text)
    for seg in segments:
        if seg.annotation is None:
            continue
        open_ann = seg.annotation
        body_start = open_ann.line_end + 1
        body_end = seg.close.line_start - 1 if seg.close is not None else total_lines

        if body_start <= line <= body_end:
            if open_ann.operator == "section":
                # Cannot retain a partial section summary or leave a section
                # open without a child node → delete the entire section block.
                _apply_cut(
                    target, node_lines, open_ann.line_start - 1, all_anns, storage
                )
            else:
                # write / edit / other: truncate the body at *line* and close
                # the tag so the block remains syntactically complete.
                close_tag = _build_close_tag(open_ann.operator, open_ann.id)
                _apply_cut(
                    target, node_lines, line, all_anns, storage, close_tag=close_tag
                )
            return

    # --- Free text (no enclosing annotation) ----------------------------------
    _apply_cut(target, node_lines, line, all_anns, storage)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_cut(
    node: NarrativeNode,
    node_lines: list[str],
    cut_line: int,
    all_anns: list[ParsedAnnotation],
    storage: Storage,
    *,
    close_tag: str | None = None,
) -> None:
    """Keep lines 1..cut_line, optionally append *close_tag*, delete orphaned section children.

    *cut_line* is 1-based inclusive.  ``cut_line=0`` means keep nothing
    (clear the file).
    """
    new_lines = node_lines[:cut_line]
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    new_text = "\n".join(new_lines)

    if close_tag is not None:
        new_text = (new_text + "\n\n" if new_text else "") + close_tag + "\n"
    elif new_text:
        new_text += "\n"

    storage.write_file(node.md_path(), new_text)

    # Delete child nodes for any section opening annotations that are now gone.
    for ann in all_anns:
        if (
            ann.line_start > cut_line
            and ann.operator == "section"
            and not ann.closing
            and not ann.self_closing
            and ann.id is not None
        ):
            _delete_node(node.child_node(ann.id), storage)


def _build_close_tag(operator: str, id: str | None) -> str:
    """Return the closing annotation string for an operator."""
    if id is not None:
        return f"[/{operator}:{id}]: #"
    return f"[/{operator}]: #"


def _clean_node_tail(node: NarrativeNode, storage: Storage) -> None:
    """Remove any unclosed ``[section:…]: #`` at the tail of *node*'s file.

    Sections cannot be open without a child node owning the cursor.  If the
    tail annotation is a section, its opening annotation is stripped from the
    file and the corresponding child node is deleted.

    Non-section annotations (e.g. an in-progress ``[write]``) are left in
    place: they do not affect the node-level cursor position.
    """
    if not node.exists():
        return

    node_text = node.md_path().read_text(encoding="utf-8")
    unclosed = find_unclosed_cursor_annotation(node_text)

    if unclosed is None or unclosed.operator != "section" or unclosed.id is None:
        return

    node_lines = node_text.split("\n")
    new_lines = node_lines[: unclosed.line_start - 1]
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    new_text = "\n".join(new_lines)
    if new_text:
        new_text += "\n"

    storage.write_file(node.md_path(), new_text)
    _delete_node(node.child_node(unclosed.id), storage)


def _delete_node(node: NarrativeNode, storage: Storage) -> None:
    """Delete *node* and all its descendants from the filesystem."""
    if not node.exists():
        return
    if node.is_leaf():
        storage.delete_file(node.md_path())
    else:
        _rmtree_via_storage(node.md_path().parent, storage)


def _rmtree_via_storage(path: Path, storage: Storage) -> None:
    """Recursively delete *path* via storage primitives."""
    if path.is_file():
        storage.delete_file(path)
    elif path.is_dir():
        for child in sorted(path.iterdir()):
            _rmtree_via_storage(child, storage)
        storage.rmdir(path)
