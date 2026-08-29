"""Stdlib-only body scanner behind ``lens kb search``.

Kept a leaf module on purpose. ``kb search`` fans body matching out to a
process pool, and on a ``spawn`` platform every worker re-imports the module
that holds the callable it was handed. Importing :mod:`lens.core.knowledge`
once per worker would cost more than the scan the worker was spawned for, so
the callable lives here, where the only imports are ``re`` and ``pathlib``.

The pattern crosses the process boundary as a source string plus flags rather
than a compiled object: compiled patterns pickle by re-compiling anyway, and
this way each worker compiles once for a whole chunk (see :func:`_compiled`).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "FileMatches",
    "build_pattern",
    "pattern_flags",
    "scan_files",
    "scan_text",
]

FileMatches = tuple[str, list[int], dict[int, str]]
"""One scanned object: its id, the 1-based lines that matched, and the text of
every line the caller needs — the matches plus whatever context was asked for.

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
    text: str, source: str, flags: int, context: int = 0
) -> tuple[list[int], dict[int, str]]:
    """Match *text* line by line; return matched line numbers and line texts.

    Line numbers are 1-based. ``line_texts`` carries every matched line plus
    *context* lines either side of each, so a caller with no access to the file
    can render grep-style context.
    """
    pattern = _compiled(source, flags)
    lines = text.split("\n")
    matched: list[int] = []
    for index, line in enumerate(lines):
        if pattern.search(line):
            matched.append(index + 1)
    if not matched:
        return [], {}
    wanted: set[int] = set()
    for lineno in matched:
        low = max(1, lineno - context)
        high = min(len(lines), lineno + context)
        wanted.update(range(low, high + 1))
    return matched, {lineno: lines[lineno - 1] for lineno in sorted(wanted)}


def scan_files(
    specs: list[tuple[str, str]], source: str, flags: int, context: int = 0
) -> list[FileMatches]:
    """Scan ``(id, path)`` pairs; return one entry per file that matched.

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
        matched, line_texts = scan_text(text, source, flags, context)
        if matched:
            out.append((canonical_id, matched, line_texts))
    return out
