"""Markdown comments and Lens operator annotations."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Any
import yaml

_COMMENT_END = re.compile(r"\]:\s*#\s*$")
_ORPHANED_COMMENT_END = re.compile(r"^\s*\]:\s*#\s*$")
_REFERENCE_LINK = re.compile(r"\]:\s*(?!\s*#\s*$)")

_ANNOTATION_RE = re.compile(
    r"^\s*\[(?P<close>/)?(?P<operator>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"(:(?P<id>[a-zA-Z0-9_-]+))?(?P<self_close>/)?\]:\s*#\s*$"
)
_ANNOTATION_OPEN_RE = re.compile(
    r"^\s*\[(?P<close>/)?(?P<operator>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"(:(?P<id>[a-zA-Z0-9_-]+))?(?P<self_close>/)?\s*$"
)
_ANNOTATION_END_RE = re.compile(r"^\s*\]:\s*#\s*$")


@dataclass
class ParsedAnnotation:
    operator: str
    id: str | None
    closing: bool
    self_closing: bool
    params: dict[str, Any]
    line_start: int
    line_end: int


def _parse_yaml_params(lines: list[str]) -> dict[str, Any]:
    if not lines:
        return {}
    try:
        return dict(yaml.safe_load("\n".join(lines)) or {})
    except Exception as e:
        warnings.warn(f"Invalid YAML: {e}", stacklevel=2)
        return {}


def _is_comment_block(lines: list[str], i: int) -> tuple[int, int] | None:
    """If line i starts a comment block, return (start, end_exclusive)."""
    if i >= len(lines):
        return None
    line = lines[i]
    stripped = line.lstrip()
    if _ORPHANED_COMMENT_END.fullmatch(line):
        return (i, i + 1)
    if not stripped.startswith("["):
        return None
    if _REFERENCE_LINK.search(line):
        return None
    if _COMMENT_END.search(line):
        return (i, i + 1)
    if i + 1 >= len(lines):
        return None
    next_line = lines[i + 1]
    if _ORPHANED_COMMENT_END.fullmatch(next_line.strip()) or (
        next_line and next_line[0] in " \t"
    ):
        j = i + 1
        while j < len(lines):
            if _COMMENT_END.search(lines[j]):
                return (i, j + 1)
            j += 1
        return (i, j)
    return None


def _try_parse_annotation(
    lines: list[str], start: int, end: int
) -> ParsedAnnotation | None:
    """If the comment block at lines[start:end] matches annotation format, parse it."""
    if start >= len(lines):
        return None
    line = lines[start]
    m = _ANNOTATION_RE.match(line)
    if m:
        params_lines: list[str] = []
        j = start + 1
        while j < end and lines[j] and lines[j][0] in " \t":
            params_lines.append(lines[j])
            j += 1
        params = _parse_yaml_params(params_lines) if params_lines else {}
        return ParsedAnnotation(
            operator=m.group("operator"),
            id=m.group("id"),
            closing=bool(m.group("close")),
            self_closing=bool(m.group("self_close")),
            params=params,
            line_start=start + 1,
            line_end=j,
        )
    m_open = _ANNOTATION_OPEN_RE.match(line)
    if m_open and not _ANNOTATION_END_RE.search(line):
        params_lines = []
        j = start + 1
        while j < end and not _ANNOTATION_END_RE.match(lines[j]):
            params_lines.append(lines[j])
            j += 1
        params = _parse_yaml_params(params_lines) if params_lines else {}
        return ParsedAnnotation(
            operator=m_open.group("operator"),
            id=m_open.group("id"),
            closing=bool(m_open.group("close")),
            self_closing=bool(m_open.group("self_close")),
            params=params,
            line_start=start + 1,
            line_end=j + 1 if j < end else j,
        )
    return None


def parse_front_matter(text: str) -> dict[str, Any]:
    """Parse front matter from the very beginning of a node. Front matter is a comment (no operator) at the start."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return {}
    block = _is_comment_block(lines, i)
    if block is None:
        return {}
    start, end = block
    if _try_parse_annotation(lines, start, end) is not None:
        return {}
    yaml_lines: list[str] = []
    for j in range(start + 1, end):
        if _ANNOTATION_END_RE.match(lines[j]):
            break
        yaml_lines.append(lines[j])
    return _parse_yaml_params(yaml_lines)


def strip_markdown_comments(text: str) -> str:
    """Remove markdown reference-style comments `[ ... ]: #` (single-line and multi-line)."""
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        block = _is_comment_block(lines, i)
        if block is not None:
            i = block[1]
            continue
        result.append(lines[i])
        i += 1
    return "\n".join(result)


def parse_annotations(text: str) -> list[ParsedAnnotation]:
    """Parse Lens operator annotations from markdown. Returns only comments matching the annotation format."""
    lines = text.split("\n")
    result: list[ParsedAnnotation] = []
    i = 0
    while i < len(lines):
        block = _is_comment_block(lines, i)
        if block is not None:
            start, end = block
            ann = _try_parse_annotation(lines, start, end)
            if ann is not None:
                result.append(ann)
            i = end
            continue
        i += 1
    return result


def parse_tail_cursor_annotation(text: str) -> ParsedAnnotation | None:
    """Check the last non-empty line of text for an open single-line cursor annotation.

    The cursor annotation is always appended as the last line of a node file, so
    scanning just the tail avoids parsing the entire file. Only single-line open
    annotations with an id qualify (multi-line or self-closing annotations do not
    represent an in-progress cursor).
    """
    for line in reversed(text.splitlines()):
        if not line.strip():
            continue
        m = _ANNOTATION_RE.match(line)
        if m and not m.group("close") and not m.group("self_close") and m.group("id"):
            return ParsedAnnotation(
                operator=m.group("operator"),
                id=m.group("id"),
                closing=False,
                self_closing=False,
                params={},
                line_start=0,
                line_end=0,
            )
        return None
    return None
