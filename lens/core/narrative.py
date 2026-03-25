"""Narrative node model: recursive node-based structure from markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lens.core.annotations import (
    ParsedAnnotation,
    parse_annotations,
    parse_front_matter,
    parse_tail_cursor_annotation,
)
from lens.core.storage import Storage

if TYPE_CHECKING:
    from lens.core.address import NarrativeAddress

# Matches the first line of any non-closing annotation that carries an ID:
#   [operator:id]: #      (single-line, including self-closing [op:id/]: #)
#   [operator:id          (first line of multi-line block)
# Does NOT match closing tags ([/operator:id]: #).
_CHILD_ID_LINE_RE = re.compile(
    r"^\[([a-zA-Z_][a-zA-Z0-9_]*):([a-zA-Z0-9_-]+)"
)


def _make_system_storage(near: Path) -> Storage:
    """Create a system-owned (owner=None) Storage for the project containing *near*.

    ``near`` is already inside a valid project (e.g. the narrative root); we
    only need to locate the enclosing git repository.
    """
    from lens.core.project import find_git_root_from
    return Storage(find_git_root_from(near))


def _read_tail_cursor_annotation(path: Path) -> ParsedAnnotation | None:
    """Read only the tail of a node file to detect an open cursor annotation.

    Seeks to the last 512 bytes so large node files are never fully read just
    to discover the cursor position.
    """
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 512))
            raw = f.read()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    if size > 512:
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
    return parse_tail_cursor_annotation(text)


@dataclass(frozen=True)
class NarrativeNode:
    narrative_root: Path
    key_path: tuple[str, ...]

    def _find_md_path(self) -> Path | None:
        if not self.key_path:
            p = self.narrative_root / "_node.md"
            return p if p.exists() else None
        parent_dir = self.narrative_root / "/".join(self.key_path[:-1])
        key = self.key_path[-1]
        folder_md = parent_dir / key / "_node.md"
        leaf_md = parent_dir / f"{key}.md"
        if folder_md.exists():
            return folder_md
        if leaf_md.exists():
            return leaf_md
        return None

    def md_path(self) -> Path:
        """Return the markdown file for this node.

        Raises ``FileNotFoundError`` if neither the folder ``_node.md`` nor the
        leaf ``.md`` file exists on disk.  Use :meth:`exists` when you need a
        boolean probe without an exception.
        """
        path = self._find_md_path()
        if path is None:
            raise FileNotFoundError(
                f"Node '{self.path_str()}' has no content file "
                f"(expected '{self.narrative_root / (self.key_path[-1] if self.key_path else '_node.md')}')"
            )
        return path

    def exists(self) -> bool:
        return self._find_md_path() is not None

    def is_folder_node(self) -> bool:
        if not self.key_path:
            return True
        parent_dir = self.narrative_root / "/".join(self.key_path[:-1])
        key = self.key_path[-1]
        return (parent_dir / key / "_node.md").exists()

    def is_leaf(self) -> bool:
        return not self.is_folder_node()

    def to_leaf(self, storage: Storage | None = None) -> None:
        """Convert folder node to leaf. Fails if folder has any files besides _node.md."""
        if not self.key_path:
            raise ValueError("root node cannot be converted to leaf")
        parent_dir = self.narrative_root / "/".join(self.key_path[:-1])
        key = self.key_path[-1]
        folder_dir = parent_dir / key
        node_md = folder_dir / "_node.md"
        leaf_md = parent_dir / f"{key}.md"
        if not node_md.exists():
            raise ValueError(f"node {key} does not exist as folder")
        if leaf_md.exists():
            raise ValueError(f"node {key} already exists as leaf")
        for p in folder_dir.iterdir():
            if p.name != "_node.md":
                raise ValueError(
                    "cannot convert to leaf: folder has other files besides _node.md"
                )
        content = node_md.read_text()
        st = storage if storage is not None else _make_system_storage(self.narrative_root)
        st.write_file(leaf_md, content)
        st.delete_file(node_md)
        st.rmdir(folder_dir)

    def to_folder(self, storage: Storage | None = None) -> None:
        """Convert leaf node to folder."""
        if not self.key_path:
            raise ValueError("root node cannot be converted to folder")
        parent_dir = self.narrative_root / "/".join(self.key_path[:-1])
        key = self.key_path[-1]
        leaf_md = parent_dir / f"{key}.md"
        folder_dir = parent_dir / key
        node_md = folder_dir / "_node.md"
        if not leaf_md.exists():
            raise ValueError(f"node {key} does not exist as leaf")
        if folder_dir.exists():
            raise ValueError(f"node {key} already exists as folder")
        content = leaf_md.read_text()
        st = storage if storage is not None else _make_system_storage(self.narrative_root)
        st.mkdir(folder_dir)
        st.write_file(node_md, content)
        st.delete_file(leaf_md)

    def child_keys(self) -> list[str]:
        # Resolve md_path once; leaf nodes (non-_node.md files) have no children.
        try:
            md = self.md_path()
        except FileNotFoundError:
            return []
        if md.name != "_node.md":
            return []
        parent = md.parent
        keys: set[str] = set()
        for p in parent.iterdir():
            if p.name == "_node.md":
                continue
            if p.is_dir():
                keys.add(p.name)
            elif p.suffix == ".md":
                keys.add(p.stem)
        valid_keys: set[str] = set()
        for k in keys:
            if (parent / k).is_dir() and (parent / k / "_node.md").exists():
                valid_keys.add(k)
            elif (parent / f"{k}.md").exists():
                valid_keys.add(k)

        # Order children by their appearance in the parent node's content.
        # Any non-closing annotation with an ID may have created a child node
        # (section, design, play, etc.), so scan for all of them.
        # valid_keys already constrains to real filesystem children.
        ordered: list[str] = []
        seen: set[str] = set()
        try:
            for line in md.read_text().splitlines():
                m = _CHILD_ID_LINE_RE.match(line)
                if m:
                    child_id = m.group(2)
                    if child_id in valid_keys and child_id not in seen:
                        ordered.append(child_id)
                        seen.add(child_id)
        except OSError:
            pass

        # Append any filesystem children not referenced in annotations.
        for k in sorted(valid_keys - seen):
            ordered.append(k)
        return ordered

    def child_node(self, key: str) -> NarrativeNode:
        return NarrativeNode(
            narrative_root=self.narrative_root,
            key_path=self.key_path + (key,),
        )

    def structural_warnings(self) -> list[str]:
        parent = self.md_path().parent
        result: list[str] = []
        for p in parent.iterdir():
            if p.name == "_node.md":
                continue
            if p.is_dir() and p.suffix != ".md":
                key = p.name
                leaf = parent / f"{key}.md"
                if leaf.exists():
                    result.append(
                        f"both {key}/ and {key}.md exist; folder wins"
                    )
        return result

    def find_cursor(self) -> NarrativeNode:
        node = self
        while True:
            ann = _read_tail_cursor_annotation(node.md_path())
            if ann is None or ann.id is None:
                return node
            child = node.child_node(ann.id)
            if not child.exists():
                return node
            node = child

    def path_str(self) -> str:
        root_name = self.narrative_root.name
        if not self.key_path:
            return root_name
        parts = [root_name] + list(self.key_path)
        return " / ".join(parts)

    def to_address(self) -> NarrativeAddress:
        """Return the canonical NarrativeAddress for this node."""
        from lens.core.address import NarrativeAddress

        return NarrativeAddress(
            narrative=self.narrative_root.name,
            key_path=self.key_path,
        )

    def find_cursor_address(self) -> NarrativeAddress:
        """Return the NarrativeAddress of the current cursor position."""
        return self.find_cursor().to_address()

    def front_matter(self) -> dict[str, Any]:
        """Parse and return front matter from the node. Empty dict if none or invalid."""
        return parse_front_matter(self.md_path().read_text())


@dataclass
class NodeSegment:
    """One logical segment of a node's content.

    A node is a flat list of segments. Each is either a free-text block
    (annotation=None) or an annotation block (annotation set).

    - Free text at end of node -> cursor is here (annotation=None, close=None)
    - Open annotation at end with close=None -> cursor is in that sub-node
    """

    annotation: ParsedAnnotation | None
    body: str
    close: ParsedAnnotation | None


def parse_segments(text: str) -> list[NodeSegment]:
    lines = text.split("\n")
    annotations = parse_annotations(text)
    ann_by_line: dict[int, ParsedAnnotation] = {
        a.line_start: a for a in annotations
    }

    # Pre-build close indices so each open annotation can find its matching close
    # in O(1) amortised rather than O(n), keeping the overall loop O(n).
    closes_by_key: dict[tuple[str, str | None], list[ParsedAnnotation]] = {}
    all_closes: list[ParsedAnnotation] = []
    for a in annotations:
        if a.closing:
            key: tuple[str, str | None] = (a.operator, a.id)
            closes_by_key.setdefault(key, []).append(a)
            all_closes.append(a)
    close_ptr: dict[tuple[str, str | None], int] = {}
    all_closes_ptr = 0

    segments: list[NodeSegment] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        line_1based = i + 1
        ann = ann_by_line.get(line_1based)

        if ann is None:
            text_lines: list[str] = [line]
            i += 1
            while i < len(lines) and ann_by_line.get(i + 1) is None:
                text_lines.append(lines[i])
                i += 1
            body = "\n".join(text_lines).rstrip()
            if body or not segments:
                segments.append(
                    NodeSegment(annotation=None, body=body, close=None)
                )
            continue

        if ann.closing:
            i = ann.line_end
            continue

        if not segments:
            segments.append(NodeSegment(annotation=None, body="", close=None))

        if ann.self_closing:
            segments.append(
                NodeSegment(annotation=ann, body="", close=ann)
            )
            i = ann.line_end
            continue

        # Advance the global closes pointer to find first_closing_after.
        while (
            all_closes_ptr < len(all_closes)
            and all_closes[all_closes_ptr].line_start <= line_1based
        ):
            all_closes_ptr += 1
        first_closing_after = (
            all_closes[all_closes_ptr] if all_closes_ptr < len(all_closes) else None
        )

        # Find the first matching close for this annotation using per-key pointer.
        ann_key: tuple[str, str | None] = (ann.operator, ann.id)
        closes = closes_by_key.get(ann_key, [])
        ptr = close_ptr.get(ann_key, 0)
        close_ann: ParsedAnnotation | None = None
        while ptr < len(closes):
            if closes[ptr].line_start > line_1based:
                close_ann = closes[ptr]
                close_ptr[ann_key] = ptr + 1
                break
            ptr += 1
        else:
            close_ptr[ann_key] = ptr

        if close_ann is not None:
            body_lines = lines[ann.line_end : close_ann.line_start - 1]
            body = "\n".join(body_lines).rstrip()
            segments.append(
                NodeSegment(
                    annotation=ann,
                    body=body,
                    close=close_ann,
                )
            )
            i = close_ann.line_end
        elif first_closing_after is not None:
            body_lines = lines[ann.line_end : first_closing_after.line_start - 1]
            body = "\n".join(body_lines).rstrip()
            segments.append(
                NodeSegment(
                    annotation=ann,
                    body=body,
                    close=None,
                )
            )
            i = first_closing_after.line_end
        else:
            body_lines = lines[ann.line_end :]
            body = "\n".join(body_lines).rstrip()
            segments.append(
                NodeSegment(
                    annotation=ann,
                    body=body,
                    close=None,
                )
            )
            i = len(lines)
    return segments


def find_unclosed_cursor_annotation(text: str) -> ParsedAnnotation | None:
    segments = parse_segments(text)
    if not segments:
        return None
    last = segments[-1]
    if last.annotation is None:
        return None
    if last.close is not None:
        return None
    return last.annotation
