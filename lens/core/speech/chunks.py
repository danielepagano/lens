"""Narrative node TTS: eligible lines, chunk ids, speak-text cleanup, cache paths."""

from __future__ import annotations

import bisect
import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from lens.core.annotations import iter_kept_storage_lines, strip_html_comments
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode

TTS_CHUNK_REVISION = 1

TTS_CHUNK_MAX_CHARS = 350
"""Heuristic span above which we look for punctuation to split; not a hard max chunk size."""

TTS_SUBCHUNK_SOFT_MIN_CHARS = 70
"""Prefer punctuation cuts that leave at least this many characters on each side when alternatives exist."""

_NONSLUG_RE = re.compile(r"[^a-z0-9]+", re.I)

_LINK_LINE_RE = re.compile(
    r"^\s*(?:!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\([^)]*\))\s*$"
)


def _words_for_chunk_id(raw_line: str) -> list[str]:
    # Word tokens only feed chunk_id strings, not where we split for TTS.
    lowered = raw_line.strip().lower()
    cleaned = _NONSLUG_RE.sub(" ", lowered).split()
    return [w for w in cleaned if w]


def chunk_id(rev: int, raw_line: str) -> str:
    """Stable id: ``chk<rev>-…--<md5>`` per backlog (words + hash of trimmed line)."""
    trimmed = raw_line.strip()
    digest = hashlib.md5(trimmed.encode("utf-8")).hexdigest()
    words = _words_for_chunk_id(trimmed)
    if not words:
        return f"chk{rev}--{digest}"

    w0 = words[0]
    if len(words) == 1:
        return f"chk{rev}-{w0}--{digest}"
    if len(words) == 2:
        return f"chk{rev}-{words[0]}--{digest}--{words[1]}"
    return f"chk{rev}-{words[0]}-{words[1]}--{digest}--{words[-1]}"


def _is_punctuation_only(s: str) -> bool:
    return bool(s) and not any(c.isalnum() for c in s)


def _is_numbers_only(s: str) -> bool:
    if not s or not any(c.isdigit() for c in s):
        return False
    return all(c.isdigit() or c.isspace() or c in ".,+-_" for c in s)


def _is_link_or_image_only_line(line: str) -> bool:
    return bool(_LINK_LINE_RE.match(line))


def is_eligible_tts_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if _is_punctuation_only(s):
        return False
    if _is_numbers_only(s):
        return False
    if _is_link_or_image_only_line(s):
        return False
    return True


_ATTRIBUTED_BLOCKQUOTE_RE = re.compile(
    r"^\s*(?:>\s*)*\[[^\]]+\]\s+(?P<rest>.+)$"
)
_HEADING_RE = re.compile(r"^\s*#+\s*")
_INLINE_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_INLINE_LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")
_EMPHASIS_RE = re.compile(r"\*\*|__|\*|_")

_FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,})")
_HTML_TAG_RE = re.compile(r"<\/?[A-Za-z][^>]*?>")
_HTML_TAGNAME_RE = re.compile(r"<\/?\s*(?P<name>[A-Za-z][A-Za-z0-9-]*)", re.I)


@dataclass(frozen=True, slots=True)
class _OpenTagState:
    name: str
    body_key: str
    open_literal: str


@dataclass(frozen=True, slots=True)
class _HtmlTagToken:
    start: int
    end: int
    name: str
    body_key: str
    open_literal: str
    is_closing: bool
    is_self_closing: bool


def _tag_body_from_literal(literal: str) -> str:
    body = literal[1:-1].strip()
    if body.startswith("/"):
        body = body[1:].lstrip()
    if body.endswith("/"):
        body = body[:-1].rstrip()
    return re.sub(r"\s+", " ", body).strip()


def _html_tag_tokens(s: str) -> list[_HtmlTagToken]:
    if "<" not in s:
        return []

    out: list[_HtmlTagToken] = []
    for m in _HTML_TAG_RE.finditer(s):
        literal = m.group(0)
        name_m = _HTML_TAGNAME_RE.match(literal)
        if not name_m:
            continue
        body = _tag_body_from_literal(literal)
        if not body:
            continue
        name = name_m.group("name").lower()
        out.append(
            _HtmlTagToken(
                start=m.start(),
                end=m.end(),
                name=name,
                body_key=body.lower(),
                open_literal=f"<{body}>",
                is_closing=literal.startswith("</"),
                is_self_closing=not literal.startswith("</")
                and literal[:-1].rstrip().endswith("/"),
            )
        )
    return out


def _matching_open_tag_index(
    stack: list[_OpenTagState], token: _HtmlTagToken
) -> int | None:
    for i in range(len(stack) - 1, -1, -1):
        if stack[i].body_key == token.body_key:
            return i
    for i in range(len(stack) - 1, -1, -1):
        if stack[i].name == token.name:
            return i
    return None


def _apply_html_tag_token(
    stack: list[_OpenTagState], token: _HtmlTagToken
) -> list[_OpenTagState]:
    if token.is_self_closing:
        return stack
    if not token.is_closing:
        stack.append(
            _OpenTagState(
                name=token.name,
                body_key=token.body_key,
                open_literal=token.open_literal,
            )
        )
        return stack

    match_idx = _matching_open_tag_index(stack, token)
    if match_idx is None:
        return stack
    return stack[:match_idx]


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ranges.sort()
    merged: list[tuple[int, int]] = []
    cur_lo, cur_hi = ranges[0]
    for lo, hi in ranges[1:]:
        if lo <= cur_hi:
            cur_hi = max(cur_hi, hi)
        else:
            merged.append((cur_lo, cur_hi))
            cur_lo, cur_hi = lo, hi
    merged.append((cur_lo, cur_hi))
    return merged


def _open_tags_at_boundaries(
    trimmed: str, boundaries: set[int]
) -> dict[int, tuple[_OpenTagState, ...]]:
    tags = _html_tag_tokens(trimmed)
    if not boundaries:
        return {}

    stack: list[_OpenTagState] = []
    states: dict[int, tuple[_OpenTagState, ...]] = {}
    tag_idx = 0
    for boundary in sorted(boundaries):
        while tag_idx < len(tags) and tags[tag_idx].end <= boundary:
            stack = _apply_html_tag_token(stack, tags[tag_idx])
            tag_idx += 1
        states[boundary] = tuple(stack)
    return states


def _repair_piece_for_tts(
    piece: str,
    open_tags_at_start: tuple[_OpenTagState, ...],
) -> str:
    prefix = "".join(tag.open_literal for tag in open_tags_at_start)
    return prefix + piece


def _is_closing_fence_line(line: str, need: int) -> bool:
    """True if *line* is a CommonMark closing fence (only backticks + optional ws), run length >= *need*."""
    s = line.rstrip("\r\n")
    lead = 0
    while lead < len(s) and s[lead] in " \t":
        lead += 1
    if lead > 3:
        return False
    i = lead
    while i < len(s) and s[i] == "`":
        i += 1
    if i - lead < need:
        return False
    return not s[i:] or s[i:].strip() == ""


def strip_fenced_code_blocks(text: str) -> str:
    """Empty out fenced code regions, preserving ``text.split("\\n")`` line count exactly.

    Openers follow CommonMark (up to 3 spaces indent, 3+ backticks, optional info
    string such as yaml or python). Only a line that is *only* a long-enough
    backtick run plus whitespace closes the block, so body lines that start with
    backticks and a language tag are not mistaken for the closer.

    Opener, body, and closing fence are each replaced by an empty string so 1-based
    line indexing into the result matches indexing into *text*. An opener with no
    closing fence is replaced by an empty string on its own line; following lines
    are preserved.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _FENCE_OPEN_RE.match(lines[i])
        if m:
            need = len(m.group("fence"))
            j = i + 1
            while j < len(lines):
                if _is_closing_fence_line(lines[j], need):
                    out.extend([""] * (j - i + 1))
                    i = j + 1
                    break
                j += 1
            else:
                out.append("")
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def strip_for_tts(line: str) -> str:
    """Plain text for TTS: drop attribution labels, light markdown stripping."""
    text = line.strip()
    while text.startswith(">"):
        text = text[1:].lstrip()

    m = _ATTRIBUTED_BLOCKQUOTE_RE.match(text)
    if m:
        text = m.group("rest").strip()

    text = _HEADING_RE.sub("", text)
    text = _INLINE_IMAGE_RE.sub("", text)
    text = _INLINE_LINK_RE.sub("", text)
    while _EMPHASIS_RE.search(text):
        text = _EMPHASIS_RE.sub("", text)
    text = text.replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass(frozen=True, slots=True)
class TtsChunk:
    raw_line: str
    id: str
    speak_text: str
    source_kept_line_1: int
    """1-based raw on-disk line number — matches ``NarrativeAddress @N``, the UI line picker, and attach."""


def _disallowed_cut_ranges_for_html(s: str) -> list[tuple[int, int]]:
    """Return disallowed cut ranges (half-open) to avoid splitting inside tag literals.

    Cuts are indices in the range ``0..len(s)`` where a subchunk boundary may occur.
    We only disallow cuts that would fall *inside* a tag literal ``<...>``.
    """
    disallowed = [
        (token.start + 1, token.end)
        for token in _html_tag_tokens(s)
        if token.start + 1 < token.end
    ]
    return _merge_ranges(disallowed)


def _cut_is_disallowed(cut: int, disallowed: list[tuple[int, int]]) -> bool:
    # disallowed is merged + sorted by lo.
    # Find the rightmost range with lo <= cut, then test membership.
    los = [lo for lo, _ in disallowed]
    i = bisect.bisect_right(los, cut) - 1
    if i < 0:
        return False
    lo, hi = disallowed[i]
    return lo <= cut < hi


def _collect_punctuation_cuts(s: str) -> list[tuple[int, int]]:
    """Indices where a sub-chunk may end: ``(cut, kind)`` with cut exclusive.

    Kind ``0`` — sentence class: isolated ``.``; maximal runs of ``?`` / ``!`` (one cut after the
    run, e.g. ``?!`` or ``!!!``). Runs of 2+ ``.`` are not sentence boundaries. Kind ``1`` — ``:``;
    kind ``2`` — ``;``. No hyphen or em-dash cuts.
    """
    out: list[tuple[int, int]] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == ".":
            j = i
            while j < n and s[j] == ".":
                j += 1
            if j - i == 1:
                out.append((i + 1, 0))
            i = j
            continue
        if c in "?!":
            j = i
            while j < n and s[j] in "?!":
                j += 1
            out.append((j, 0))
            i = j
            continue
        if c == ":":
            out.append((i + 1, 1))
        elif c == ";":
            out.append((i + 1, 2))
        i += 1
    return out


def _pick_punctuation_cut(
    lo: int,
    hi: int,
    cuts: list[tuple[int, int]],
) -> int | None:
    mid = (lo + hi) // 2
    inner = [(cut, kind) for cut, kind in cuts if lo < cut < hi]
    if not inner:
        return None

    def soft_ok(cut: int) -> bool:
        return (
            cut - lo >= TTS_SUBCHUNK_SOFT_MIN_CHARS
            and hi - cut >= TTS_SUBCHUNK_SOFT_MIN_CHARS
        )

    preferred = [(c, k) for c, k in inner if soft_ok(c)]
    pool = preferred if preferred else inner
    cut, _kind = min(pool, key=lambda t: (t[1], abs(t[0] - mid)))
    return cut


def _split_piece_ranges(lo: int, hi: int, cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if hi - lo <= TTS_CHUNK_MAX_CHARS:
        return [(lo, hi)]
    cut = _pick_punctuation_cut(lo, hi, cuts)
    if cut is None:
        return [(lo, hi)]
    return _split_piece_ranges(lo, cut, cuts) + _split_piece_ranges(cut, hi, cuts)


def _plan_line_piece_ranges(trimmed: str) -> list[tuple[int, int]]:
    if len(trimmed) <= TTS_CHUNK_MAX_CHARS:
        return [(0, len(trimmed))]
    cuts = _collect_punctuation_cuts(trimmed)
    disallowed = _disallowed_cut_ranges_for_html(trimmed)
    if disallowed:
        cuts = [(cut, kind) for cut, kind in cuts if not _cut_is_disallowed(cut, disallowed)]
    return _split_piece_ranges(0, len(trimmed), cuts)


def chunks_by_kept_line(chunks: Iterable[TtsChunk]) -> dict[int, list[TtsChunk]]:
    out: dict[int, list[TtsChunk]] = {}
    for ch in chunks:
        out.setdefault(ch.source_kept_line_1, []).append(ch)
    return out


def iter_raw_storage_text(node: NarrativeNode) -> str:
    return node.md_path().read_text(encoding="utf-8")


def slice_storage_text_by_disk_lines(
    storage_text: str,
    line_start_1: int | None,
    line_end_1: int | None,
) -> str:
    """Keep only physical lines ``line_start_1`` … ``line_end_1`` (1-based, inclusive).

    Matches narrative addresses like ``@12`` (single line) or ``@12:40`` (range).
    If ``line_start_1`` is ``None``, returns *storage_text* unchanged.
    """
    if line_start_1 is None:
        return storage_text
    if line_start_1 < 1:
        raise LensException("line number must be >= 1")
    lines = storage_text.split("\n")
    n = len(lines)
    lo = line_start_1
    hi = line_end_1 if line_end_1 is not None else line_start_1
    if hi < lo:
        raise LensException("line range end is before start")
    if lo > n:
        return ""
    hi = min(hi, n)
    segment = lines[lo - 1 : hi]
    return "\n".join(segment)


def tts_cache_mount_prefix(node: NarrativeNode) -> str:
    """Mount-relative directory for this node's TTS cache (posix-style, no leading slash)."""
    parts = ("tts-cache", node.narrative_root.name) + node.key_path
    return "/".join(parts)


def speech_kept_storage_lines(
    storage_text: str,
    *,
    line_start_1: int | None = None,
    line_end_1: int | None = None,
) -> list[tuple[str, int]]:
    """Kept storage lines with the same preprocessing as :func:`chunks_for_node_text`.

    Optional *line_start_1* / *line_end_1* slice physical lines before stripping (same as
    chunking). Then HTML comments and fenced code blocks are emptied (line count preserved),
    then annotation / markdown comment blocks are skipped via :func:`iter_kept_storage_lines`.
    The returned ``disk_line_1based`` value is 1-based within the (possibly sliced) buffer;
    callers that slice must add ``(line_start_1 - 1)`` to recover absolute on-disk lines.
    """
    segment = slice_storage_text_by_disk_lines(storage_text, line_start_1, line_end_1)
    cleaned = strip_fenced_code_blocks(strip_html_comments(segment))
    return iter_kept_storage_lines(cleaned)


def tts_chunks_for_eligible_trimmed_line(
    trimmed: str,
    source_kept_line_1: int,
) -> list[TtsChunk]:
    """Sub-chunk one eligible kept line using the same rules as :func:`chunks_for_node_text`."""
    cuts = _plan_line_piece_ranges(trimmed)
    boundary_states = _open_tags_at_boundaries(
        trimmed,
        {0, len(trimmed)} | {boundary for piece in cuts for boundary in piece},
    )
    out: list[TtsChunk] = []
    for lo, hi in cuts:
        piece = trimmed[lo:hi].strip()
        if not piece:
            continue
        repaired = _repair_piece_for_tts(piece, boundary_states[lo])
        speak = strip_for_tts(repaired)
        if not speak:
            continue
        cid = chunk_id(TTS_CHUNK_REVISION, piece)
        out.append(
            TtsChunk(
                raw_line=piece,
                id=cid,
                speak_text=speak,
                source_kept_line_1=source_kept_line_1,
            )
        )
    return out


def chunks_for_node_text(
    storage_text: str,
    *,
    line_start_1: int | None = None,
    line_end_1: int | None = None,
) -> list[TtsChunk]:
    """Split storage into eligible kept lines; long lines become multiple sub-chunks.

    Uses :func:`speech_kept_storage_lines` for preprocessing, then eligibility, length checks,
    and ids. Optional *line_start_1* / *line_end_1* restrict to a physical line slice of the
    file (before HTML strip), same numbering as
    :class:`~lens.core.address.NarrativeAddress`. :attr:`TtsChunk.source_kept_line_1` is the
    1-based raw on-disk line number — slicing offsets are added back so callers get absolute
    file lines regardless of slicing.
    """
    kept = speech_kept_storage_lines(
        storage_text, line_start_1=line_start_1, line_end_1=line_end_1
    )
    offset = (line_start_1 - 1) if line_start_1 is not None else 0
    out: list[TtsChunk] = []
    for line, disk in kept:
        if not is_eligible_tts_line(line):
            continue
        out.extend(tts_chunks_for_eligible_trimmed_line(line.strip(), disk + offset))
    return out


def chunks_for_node(
    node: NarrativeNode,
    *,
    line_start_1: int | None = None,
    line_end_1: int | None = None,
) -> list[TtsChunk]:
    return chunks_for_node_text(
        iter_raw_storage_text(node),
        line_start_1=line_start_1,
        line_end_1=line_end_1,
    )
