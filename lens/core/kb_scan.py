"""Stdlib-only body scanner behind ``lens kb search``.

Kept a leaf module on purpose. ``kb search`` fans body matching out to a
process pool, and on a ``spawn`` platform every worker re-imports the module
that holds the callable it was handed. Importing :mod:`lens.core.knowledge`
once per worker would cost more than the scan the worker was spawned for, so
the callable lives here, where the only imports are ``re`` and ``pathlib``.

Patterns cross the process boundary as ``(source, flags)`` pairs rather than
compiled objects: compiled patterns pickle by re-compiling anyway, and this way
each worker compiles once for a whole chunk (see :func:`_compiled`). Flags
travel per pattern because smart case decides them per pattern — ``-e Murgin
-e inn`` is one case-sensitive pattern and one that is not.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "FileMatches",
    "ScanPattern",
    "build_pattern",
    "has_uppercase",
    "pattern_flags",
    "scan_files",
    "scan_text",
]

ScanPattern = tuple[str, int]
"""A regex source and its ``re`` flags."""

FileMatches = tuple[str, list[int], dict[int, str], list[int]]
"""One scanned object: its id, the 1-based lines that matched any pattern, the
text of every line the caller needs — the matches plus whatever context was
asked for — and the indexes of the patterns that matched at least one line.

The last field is what makes AND possible across a process boundary. A file
that matches only some of the patterns still comes back, because the missing
ones may yet match the object's id or tags, which the worker never sees.

A plain tuple of builtins on purpose: this is what comes back across the
process boundary, once per file that matched, and it pickles as fast as
anything can."""


def build_pattern(
    pattern: str,
    *,
    fixed_string: bool = False,
    word: bool = False,
) -> str:
    """Return the regex source for a user pattern under ``-F`` / ``-w``.

    Word mode wraps in a non-capturing group first, so ``-w 'a|b'`` means
    "the whole word ``a`` or the whole word ``b``" rather than "word-start
    ``a``, or ``b`` word-end".
    """
    source = re.escape(pattern) if fixed_string else pattern
    if word:
        source = rf"\b(?:{source})\b"
    return source


def pattern_flags(*, ignore_case: bool = False) -> int:
    return re.IGNORECASE if ignore_case else 0


_ESCAPE = re.compile(r"\\.")


def has_uppercase(pattern: str, *, fixed_string: bool = False) -> bool:
    """Whether *pattern* asks for an uppercase letter — the smart-case test.

    In a regex, an escape is not a literal: ``\\S`` and ``\\W`` are classes,
    and must not turn ``\\Sgrave`` case-sensitive. A fixed string has no escapes.
    """
    literal = pattern if fixed_string else _ESCAPE.sub("", pattern)
    return any(char.isupper() for char in literal)


_COMPILED: dict[tuple[str, int], re.Pattern[str]] = {}


def _compiled(source: str, flags: int) -> re.Pattern[str]:
    """Compile once per (source, flags) per process.

    ``re``'s own cache would mostly do this, but it is bounded and shared with
    every other pattern the process uses; a worker scanning thousands of files
    must not be one eviction away from recompiling per file.
    """
    key = (source, flags)
    cached = _COMPILED.get(key)
    if cached is None:
        cached = re.compile(source, flags)
        _COMPILED[key] = cached
    return cached


def scan_text(
    text: str, patterns: list[ScanPattern], context: int = 0
) -> tuple[list[int], dict[int, str], list[int]]:
    """Match *text* line by line against every pattern.

    Returns the 1-based lines any pattern matched, their texts, and the indexes
    of the patterns that matched somewhere. ``line_texts`` carries every matched
    line plus *context* lines either side of each, so a caller with no access
    to the file can render grep-style context.
    """
    compiled = [_compiled(source, flags) for source, flags in patterns]
    lines = text.split("\n")
    matched: list[int] = []
    seen: set[int] = set()
    for index, line in enumerate(lines):
        hit = False
        for position, pattern in enumerate(compiled):
            if pattern.search(line):
                hit = True
                seen.add(position)
        if hit:
            matched.append(index + 1)
    if not matched:
        return [], {}, []
    wanted: set[int] = set()
    for lineno in matched:
        low = max(1, lineno - context)
        high = min(len(lines), lineno + context)
        wanted.update(range(low, high + 1))
    return (
        matched,
        {lineno: lines[lineno - 1] for lineno in sorted(wanted)},
        sorted(seen),
    )


def scan_files(
    specs: list[tuple[str, str]], patterns: list[ScanPattern], context: int = 0
) -> list[FileMatches]:
    """Scan ``(id, path)`` pairs; return one entry per file any pattern matched.

    Unreadable files are skipped rather than raised on: a knowledge tree can
    hold a stray binary or a file whose permissions changed, and a search is
    the wrong place to fail the whole run over one of them.
    """
    out: list[FileMatches] = []
    for canonical_id, path in specs:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        matched, line_texts, seen = scan_text(text, patterns, context)
        if matched:
            out.append((canonical_id, matched, line_texts, seen))
    return out
