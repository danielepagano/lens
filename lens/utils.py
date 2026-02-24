"""Shared utilities for Lens."""

from __future__ import annotations

import re

_COMMENT_END = re.compile(r"\]:\s*#\s*$")
_ORPHANED_COMMENT_END = re.compile(r"^\s*\]:\s*#\s*$")
_REFERENCE_LINK = re.compile(r"\]:\s*(?!\s*#\s*$)")


def strip_markdown_comments(text: str) -> str:
    """Remove markdown reference-style comments `[ ... ]: #` (single-line and multi-line)."""
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if _ORPHANED_COMMENT_END.fullmatch(line):
            i += 1
            continue
        if stripped.startswith("["):
            if _COMMENT_END.search(line):
                i += 1
                continue
            if _REFERENCE_LINK.search(line):
                result.append(line)
                i += 1
                continue
            if i + 1 >= len(lines):
                result.append(line)
                i += 1
                continue
            next_line = lines[i + 1]
            if _ORPHANED_COMMENT_END.fullmatch(next_line.strip()) or (
                next_line and next_line[0] in " \t"
            ):
                i += 1
                while i < len(lines):
                    if _COMMENT_END.search(lines[i]):
                        i += 1
                        break
                    i += 1
                continue
            result.append(line)
            i += 1
            continue
        result.append(line)
        i += 1
    return "\n".join(result)
