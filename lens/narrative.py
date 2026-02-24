"""Narrative node model: recursive node-based structure from markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

_ANNOTATION_RE = re.compile(
    r"^\s*\[(?P<close>/)?(?P<operator>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"(:(?P<id>[a-zA-Z0-9_-]+))?(?P<self_close>/)?\]:\s*#\s*$"
)
_ANNOTATION_OPEN_RE = re.compile(
    r"^\s*\[(?P<close>/)?(?P<operator>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"(:(?P<id>[a-zA-Z0-9_-]+))?(?P<self_close>/)?\s*$"
)
_ANNOTATION_END_RE = re.compile(r"^\s*\]:\s*#\s*$")


@dataclass(frozen=True)
class NarrativeNode:
    narrative_root: Path
    key_path: tuple[str, ...]


@dataclass
class ParsedAnnotation:
    operator: str
    id: str | None
    closing: bool
    self_closing: bool
    params: dict[str, Any]
    line_start: int
    line_end: int


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


def node_md_path(node: NarrativeNode) -> Path | None:
    if not node.key_path:
        p = node.narrative_root / "_node.md"
        return p if p.exists() else None
    parent_dir = node.narrative_root / "/".join(node.key_path[:-1])
    key = node.key_path[-1]
    folder_md = parent_dir / key / "_node.md"
    leaf_md = parent_dir / f"{key}.md"
    if folder_md.exists():
        return folder_md
    if leaf_md.exists():
        return leaf_md
    return None


def node_exists(node: NarrativeNode) -> bool:
    return node_md_path(node) is not None


def is_folder_node(node: NarrativeNode) -> bool:
    if not node.key_path:
        return True
    parent_dir = node.narrative_root / "/".join(node.key_path[:-1])
    key = node.key_path[-1]
    return (parent_dir / key / "_node.md").exists()


def child_keys(node: NarrativeNode) -> list[str]:
    md_path = node_md_path(node)
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


def child_node(node: NarrativeNode, key: str) -> NarrativeNode:
    return NarrativeNode(
        narrative_root=node.narrative_root,
        key_path=node.key_path + (key,),
    )


def structural_warnings(node: NarrativeNode) -> list[str]:
    md_path = node_md_path(node)
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


def _parse_yaml_params(lines: list[str]) -> dict[str, Any]:
    if not lines:
        return {}
    try:
        import yaml
        return dict(yaml.safe_load("\n".join(lines)) or {})
    except Exception:
        return {}


def parse_annotations(text: str) -> list[ParsedAnnotation]:
    lines = text.split("\n")
    result: list[ParsedAnnotation] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _ANNOTATION_RE.match(line)
        if m:
            params_lines: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j] and lines[j][0] in " \t":
                params_lines.append(lines[j])
                j += 1
            params = _parse_yaml_params(params_lines) if params_lines else {}
            result.append(
                ParsedAnnotation(
                    operator=m.group("operator"),
                    id=m.group("id"),
                    closing=bool(m.group("close")),
                    self_closing=bool(m.group("self_close")),
                    params=params,
                    line_start=i + 1,
                    line_end=j,
                )
            )
            i = j
            continue
        m_open = _ANNOTATION_OPEN_RE.match(line)
        if m_open and not _ANNOTATION_END_RE.search(line):
            params_lines = []
            j = i + 1
            while j < len(lines) and not _ANNOTATION_END_RE.match(lines[j]):
                params_lines.append(lines[j])
                j += 1
            if j < len(lines):
                j += 1
            params = _parse_yaml_params(params_lines) if params_lines else {}
            result.append(
                ParsedAnnotation(
                    operator=m_open.group("operator"),
                    id=m_open.group("id"),
                    closing=bool(m_open.group("close")),
                    self_closing=bool(m_open.group("self_close")),
                    params=params,
                    line_start=i + 1,
                    line_end=j,
                )
            )
            i = j
            continue
        i += 1
    return result


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
        for a in annotations:
            if (
                a.closing
                and a.operator == ann.operator
                and a.id == ann.id
                and a.line_start > line_1based
            ):
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


def find_cursor(root: NarrativeNode) -> NarrativeNode:
    node = root
    while True:
        path = node_md_path(node)
        if path is None:
            return node
        ann = find_unclosed_cursor_annotation(path.read_text())
        if ann is None or ann.id is None:
            return node
        child = child_node(node, ann.id)
        if not node_exists(child):
            return node
        node = child


def cursor_path_str(node: NarrativeNode) -> str:
    root_name = node.narrative_root.name
    if not node.key_path:
        return root_name
    parts = [root_name] + list(node.key_path)
    return " / ".join(parts)


def get_active_narrative(project_root: Path) -> NarrativeNode | None:
    import tomllib

    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        return None
    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)
    raw_project = config.get("project")
    if not isinstance(raw_project, dict):
        return None
    project = cast(dict[str, Any], raw_project)
    narrative = project.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return None
    narrative_dir = project_root / "narrative" / narrative
    if not narrative_dir.exists() or not narrative_dir.is_dir():
        return None
    return NarrativeNode(narrative_root=narrative_dir, key_path=())
