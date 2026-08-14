"""Markdown comments and Lens operator annotations."""

from __future__ import annotations

import codecs
import re
import warnings
from dataclasses import dataclass
from typing import Any
import yaml

_COMMENT_END = re.compile(r"\]:\s*#\s*$")
_ORPHANED_COMMENT_END = re.compile(r"^\s*\]:\s*#\s*$")
_REFERENCE_LINK = re.compile(r"\]:\s*(?!\s*#\s*$)")

ANNOTATION_RE = re.compile(
    r"^\s*\[(?P<close>/)?(?P<operator>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"(:(?P<id>[a-zA-Z0-9_-]+))?(?P<self_close>/)?\]:\s*#\s*$"
)
ANNOTATION_OPEN_RE = re.compile(
    r"^\s*\[(?P<close>/)?(?P<operator>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"(:(?P<id>[a-zA-Z0-9_-]+))?(?P<self_close>/)?\s*$"
)
_ANNOTATION_END_RE = re.compile(r"^\s*\]:\s*#\s*$")
MENTION_LINE_RE = re.compile(
    r"^\s*\[(?P<kind>mention|include):\s*(?P<id>[^\s\]]+)\s*\]:\s*#\s*$"
)
"""One ``[mention: id]: #`` / ``[include: id]: #`` line (see :mod:`lens.core.mentions`).

Defined here rather than there because the annotation grammar has to *know*
about the form to ignore it properly: these are inert comments, and inert has
to mean "skipped by the tail scan" — a scan that merely fails to recognise one
reports no open annotation at all, which silently moves the cursor up out of an
open session.
"""

_AI_SECRET_RE = re.compile(
    r"<!--\s*ai:secret:\s*([\s\S]*?)\s*-->",
    re.MULTILINE,
)
_AI_SECRET_OPEN_RE = re.compile(r"<!--\s*ai:secret:\s*")

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
    m = ANNOTATION_RE.match(line)
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
    m_open = ANNOTATION_OPEN_RE.match(line)
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


def find_front_matter_span(text: str) -> tuple[int, int] | None:
    """Return (start_line_0based, end_exclusive_0based) of the front matter comment block, or None."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None
    block = _is_comment_block(lines, i)
    if block is None:
        return None
    start, end = block
    if _try_parse_annotation(lines, start, end) is not None:
        return None
    return (start, end)


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


def pop_front_matter_key(text: str, key: str) -> tuple[Any, str]:
    """Extract *key* from the leading front-matter comment block, if present.

    Returns ``(value, remaining_text)``: *value* is the raw YAML value for
    *key* (``None`` if there is no front matter or the key is absent), and
    *remaining_text* is *text* with that key's line(s) removed from the
    front-matter block — other keys are left untouched, and the whole block
    is dropped if nothing else remains. When *value* is ``None``,
    *remaining_text* equals *text* unchanged.
    """
    span = find_front_matter_span(text)
    if span is None:
        return None, text
    fm = parse_front_matter(text)
    if key not in fm:
        return None, text

    lines = text.split("\n")
    start, end = span
    key_re = re.compile(rf"^(\s*){re.escape(key)}\s*:")
    param_lines = lines[start + 1 : end - 1]

    # Only a line at the block's own top-level indent can be *the* key to pop —
    # a same-named key nested under some other top-level key (e.g. `meta:` /
    # `  tags: ...`) is that other key's value, not a sibling to remove.
    base_indent: int | None = None
    for line in param_lines:
        if line.strip():
            base_indent = len(line) - len(line.lstrip(" "))
            break

    kept: list[str] = []
    skip_indent: int | None = None
    for line in param_lines:
        if skip_indent is not None:
            indent = len(line) - len(line.lstrip(" "))
            if line.strip() and indent <= skip_indent:
                skip_indent = None
            else:
                continue
        m = key_re.match(line)
        if m and len(m.group(1)) == base_indent:
            skip_indent = len(m.group(1))
            continue
        kept.append(line)

    if kept:
        new_lines = lines[: start + 1] + kept + lines[end - 1 :]
    else:
        new_lines = lines[:start] + lines[end:]

    return fm[key], "\n".join(new_lines)


def iter_kept_storage_lines(raw: str) -> list[tuple[str, int]]:
    """Lines kept by :func:`strip_markdown_comments` with 1-based physical line numbers.

    Each tuple is ``(line_text, disk_line_1based)`` for one logical row in the
    storage file after skipping markdown comment / annotation blocks — same
    walk as :func:`strip_markdown_comments`, without joining.
    """
    lines = raw.split("\n")
    result: list[tuple[str, int]] = []
    i = 0
    while i < len(lines):
        block = _is_comment_block(lines, i)
        if block is not None:
            i = block[1]
            continue
        result.append((lines[i], i + 1))
        i += 1
    return result


def strip_markdown_comments(text: str) -> str:
    """Remove markdown reference-style comments `[ ... ]: #` (single-line and multi-line)."""
    kept = iter_kept_storage_lines(text)
    return "\n".join(t for t, _ in kept)


_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")


def strip_html_comments(text: str) -> str:
    """Remove HTML comments ``<!-- ... -->``, preserving line count.

    Each removed match is replaced by as many ``\\n`` characters as the match consumed,
    so 1-based line indexing into the result matches indexing into *text*.
    """
    def _replace(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    return _HTML_COMMENT_RE.sub(_replace, text)


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
    """Check the tail of text for an open cursor annotation at the end.

    The cursor annotation is always appended at the end of a node file, so
    scanning just the tail avoids parsing the entire file. Handles both
    single-line [operator:id]: # and multi-line open annotations with params.
    """
    lines = text.splitlines()
    i = len(lines) - 1
    # Mentions and includes are appended at a node's tail and must not mask the
    # open annotation above them, so they are skipped exactly like blank lines.
    while i >= 0 and (not lines[i].strip() or MENTION_LINE_RE.match(lines[i])):
        i -= 1
    if i < 0:
        return None
    last_nonempty = lines[i]

    m = ANNOTATION_RE.match(last_nonempty)
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

    if not _ANNOTATION_END_RE.match(last_nonempty):
        return None

    for j in range(i - 1, -1, -1):
        line = lines[j]
        if not line.strip():
            continue
        m_open = ANNOTATION_OPEN_RE.match(line)
        if m_open and not _ANNOTATION_END_RE.search(line):
            if (
                m_open.group("id")
                and not m_open.group("close")
                and not m_open.group("self_close")
            ):
                return ParsedAnnotation(
                    operator=m_open.group("operator"),
                    id=m_open.group("id"),
                    closing=False,
                    self_closing=False,
                    params={},
                    line_start=0,
                    line_end=0,
                )
            return None
        if line and line[0] in " \t":
            continue
        return None
    return None


def _rot13(s: str) -> str:
    return codecs.encode(s, "rot_13")


def encode_ai_secrets(text: str) -> str:
    """ROT13-encode the content inside each ``<!-- ai:secret: ... -->`` block.

    **The transform is an involution** — :func:`decode_ai_secrets` *is* this
    function — so applying it an even number of times yields plaintext.  That
    makes the direction of every call site load-bearing.  The system-wide
    contract is:

    *  **Storage form** (narrative files, KB objects): secrets encoded.
    *  **Model form** (anything sent to or received from an LLM): decoded.

    Text therefore crosses the boundary exactly once per direction.  Decoding
    happens in :class:`~lens.core.crawl_transforms.SecretDecodeTransform` for
    the crawl graph and in ``lens.core.command_tools`` for inline command-tool
    results; encoding happens in :func:`encode_ai_secrets_for_persist` on LLM
    output and on model-authored ``kb_patch`` content.  Adding a new path that
    shows stored KB text to a model, or writes model text to storage, means
    adding the matching conversion — a missing *or* duplicated one silently
    leaks plaintext (issue #74).
    """

    def repl(match: re.Match[str]) -> str:
        content = match.group(1)
        return f"<!-- ai:secret:\n{_rot13(content)}\n-->"

    return _AI_SECRET_RE.sub(repl, text)


def encode_ai_secrets_for_persist(text: str, *, inside_secret: bool = False) -> str:
    """Encode *text* for storage, including a half of a block split across chunks.

    Use this on LLM-authored text.  A generation can be cut in half between the
    opening ``<!-- ai:secret:`` and its ``-->`` — by a command-tool round
    boundary, a stop sequence, or an interrupt — and neither half matches
    :func:`encode_ai_secrets`, so the plaintext would survive to disk.  Both
    halves are handled, and they need different treatment:

    *  A **dangling opener** encodes to end of text.
    *  *inside_secret* says this text *begins* mid-block, because the opener
       arrived in an earlier chunk.  Everything up to the first ``-->``
       encodes, and the remainder is ordinary text again.

    Callers that chunk a single generation must therefore thread the flag
    forward — :func:`ends_inside_ai_secret` computes it.  Rewrites are in place
    (no whitespace normalisation) so both branches stay length-preserving like
    the paired form.  ``-->`` survives ROT13 unchanged and cannot be created by
    it, so the marker positions are the same before and after encoding.

    :func:`decode_ai_secrets` deliberately does *not* mirror this: stored text
    with a dangling opener is malformed, and decoding it to end of file would
    garble whole nodes.  :func:`decode_ai_secrets_for_model` is the mirror for
    the one caller that legitimately holds a split block.
    """
    if inside_secret:
        close = text.find("-->")
        if close < 0:
            return _rot13(text)
        return _rot13(text[:close]) + encode_ai_secrets_for_persist(text[close:])
    encoded = encode_ai_secrets(text)
    last_open: re.Match[str] | None = None
    for match in _AI_SECRET_OPEN_RE.finditer(encoded):
        last_open = match
    if last_open is None:
        return encoded
    tail = encoded[last_open.end() :]
    if "-->" in tail:
        return encoded
    return encoded[: last_open.end()] + _rot13(tail)


def ends_inside_ai_secret(text: str, *, inside_secret: bool = False) -> bool:
    """Report whether *text* ends inside an ``ai:secret`` block that never closed.

    Feed the result back as *inside_secret* for the next chunk of the same
    generation; see :func:`encode_ai_secrets_for_persist`.  Safe to call on
    either the raw or the encoded form of a chunk — encoding leaves every
    marker this scans byte-identical, except in the case that returns ``True``
    on both forms anyway (a whole chunk swallowed by an open block).
    """
    if inside_secret:
        close = text.find("-->")
        if close < 0:
            return True
        return ends_inside_ai_secret(text[close + len("-->") :])
    last_open: re.Match[str] | None = None
    for match in _AI_SECRET_OPEN_RE.finditer(text):
        last_open = match
    return last_open is not None and "-->" not in text[last_open.end() :]


def decode_ai_secrets(text: str) -> str:
    """ROT13-decode the content inside each ``<!-- ai:secret: ... -->`` block.

    See :func:`encode_ai_secrets` for the storage-form/model-form contract.
    """
    return encode_ai_secrets(text)


def decode_ai_secrets_for_model(text: str, *, inside_secret: bool = False) -> str:
    """Decode LLM-authored text back to model form, split blocks included.

    The mirror of :func:`encode_ai_secrets_for_persist`, for the one caller that
    holds a legitimately split block: an assistant turn being replayed to the
    model that wrote it.  Everywhere else a dangling opener means malformed
    storage, so use :func:`decode_ai_secrets` and leave it alone.
    """
    return encode_ai_secrets_for_persist(text, inside_secret=inside_secret)