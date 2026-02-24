"""Narrative node model: recursive node-based structure from markdown files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lens.annotations import ParsedAnnotation, parse_annotations


@dataclass(frozen=True)
class NarrativeNode:
    narrative_root: Path
    key_path: tuple[str, ...]

    def md_path(self) -> Path | None:
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

    def exists(self) -> bool:
        return self.md_path() is not None

    def is_folder_node(self) -> bool:
        if not self.key_path:
            return True
        parent_dir = self.narrative_root / "/".join(self.key_path[:-1])
        key = self.key_path[-1]
        return (parent_dir / key / "_node.md").exists()

    def is_leaf(self) -> bool:
        return not self.is_folder_node()

    def to_leaf(self) -> None:
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
        leaf_md.write_text(content)
        node_md.unlink()
        folder_dir.rmdir()

    def to_folder(self) -> None:
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
        folder_dir.mkdir(parents=True)
        node_md.write_text(content)
        leaf_md.unlink()

    def child_keys(self) -> list[str]:
        md_path = self.md_path()
        if md_path is None:
            return []
        parent = md_path.parent
        keys: set[str] = set()
        for p in parent.iterdir():
            if p.name == "_node.md":
                continue
            if p.is_dir():
                keys.add(p.name)
            elif p.suffix == ".md":
                keys.add(p.stem)
        result: list[str] = []
        seen: set[str] = set()
        for k in sorted(keys):
            if k in seen:
                continue
            seen.add(k)
            if (parent / k).is_dir() and (parent / k / "_node.md").exists():
                result.append(k)
            elif (parent / f"{k}.md").exists():
                result.append(k)
        return result

    def child_node(self, key: str) -> NarrativeNode:
        return NarrativeNode(
            narrative_root=self.narrative_root,
            key_path=self.key_path + (key,),
        )

    def structural_warnings(self) -> list[str]:
        md_path = self.md_path()
        if md_path is None:
            return []
        parent = md_path.parent
        warnings: list[str] = []
        for p in parent.iterdir():
            if p.name == "_node.md":
                continue
            if p.is_dir() and p.suffix != ".md":
                key = p.name
                leaf = parent / f"{key}.md"
                if leaf.exists():
                    warnings.append(
                        f"both {key}/ and {key}.md exist; folder wins"
                    )
        return warnings

    def find_cursor(self) -> NarrativeNode:
        node = self
        while True:
            path = node.md_path()
            if path is None:
                return node
            ann = find_unclosed_cursor_annotation(path.read_text())
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

        close_ann: ParsedAnnotation | None = None
        first_closing_after: ParsedAnnotation | None = None
        for a in annotations:
            if not a.closing or a.line_start <= line_1based:
                continue
            if first_closing_after is None:
                first_closing_after = a
            if a.operator == ann.operator and a.id == ann.id:
                close_ann = a
                break

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
