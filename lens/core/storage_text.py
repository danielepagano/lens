"""Shared storage-to-LLM text normalization helpers.

This module centralizes the transformations used when rendering markdown
storage files for prompt consumption and line-addressed tooling.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lens.core.annotations import (
    decode_ai_secrets,
    iter_kept_storage_lines,
    strip_html_comments,
)
from lens.core.exceptions import LensException


class StorageNormalizationError(LensException):
    """Raised when normalization invariants are violated."""


@dataclass(frozen=True)
class StorageLlmView:
    """Storage text as the LLM sees it plus line mapping to disk lines."""

    visible_for_llm: str
    disk_line_start_1based: tuple[int, ...]
    disk_line_end_1based: tuple[int, ...]


@dataclass(frozen=True)
class NormalizedStorageText:
    """Canonical projections of a storage markdown buffer."""

    raw_storage_text: str
    strip_comments_text: str
    llm_view: StorageLlmView

    @property
    def llm_visible_text(self) -> str:
        return self.llm_view.visible_for_llm


def _split_lines(text: str) -> tuple[list[str], bool]:
    if text == "":
        return [], False
    had_trailing = text.endswith(("\n", "\r\n", "\r"))
    return text.splitlines(), had_trailing


def _kept_char_intervals(kept: list[str]) -> list[tuple[int, int]]:
    acc = 0
    out: list[tuple[int, int]] = []
    for k, ln in enumerate(kept):
        start = acc
        end_excl = acc + len(ln)
        out.append((start, end_excl))
        acc = end_excl
        if k < len(kept) - 1:
            acc += 1
    return out


def _char_pos_to_disk(intervals: list[tuple[int, int]], disk: list[int], pos: int) -> int:
    for k, (a, b) in enumerate(intervals):
        if a == b == pos:
            return disk[k]
        if a <= pos < b:
            return disk[k]
        if pos == b and k + 1 < len(intervals):
            return disk[k + 1]
    raise StorageNormalizationError(
        f"internal: character offset {pos} is not inside any kept storage line span"
    )


def _char_starts_from_splitlines_rows(
    decoded: str, rows: list[str], had_trailing: bool
) -> list[int]:
    if not rows:
        if decoded:
            raise StorageNormalizationError("internal: non-empty decoded with empty rows")
        return []
    starts: list[int] = []
    pos = 0
    for i, rl in enumerate(rows):
        starts.append(pos)
        pos += len(rl)
        if i < len(rows) - 1:
            if pos >= len(decoded):
                raise StorageNormalizationError(
                    "internal: missing newline between decoded rows"
                )
            if decoded.startswith("\r\n", pos):
                pos += 2
            elif decoded[pos] in "\n\r":
                pos += 1
            else:
                raise StorageNormalizationError(
                    f"internal: expected newline after row {i} in decoded buffer"
                )
    if had_trailing and pos < len(decoded):
        if decoded.startswith("\r\n", pos):
            pos += 2
        elif decoded[pos] in "\n\r":
            pos += 1
    if pos != len(decoded):
        raise StorageNormalizationError(
            "internal: decoded row offsets do not cover full string "
            f"(left {len(decoded) - pos} bytes)"
        )
    return starts


def normalize_storage_text(raw_storage_text: str) -> NormalizedStorageText:
    """Build canonical views for one raw storage markdown buffer."""
    kept_pairs = iter_kept_storage_lines(raw_storage_text)
    if not kept_pairs:
        return NormalizedStorageText(
            raw_storage_text=raw_storage_text,
            strip_comments_text="",
            llm_view=StorageLlmView("", (), ()),
        )

    kept = [t for t, _ in kept_pairs]
    disk = [n for _, n in kept_pairs]
    strip_comments = "\n".join(kept)
    decoded = decode_ai_secrets(strip_comments)
    if len(strip_comments) != len(decoded):
        raise StorageNormalizationError(
            "decode_ai_secrets changed byte length; cannot map anchors to storage lines"
        )

    res_lines, had_tr = _split_lines(decoded)
    starts = _char_starts_from_splitlines_rows(decoded, res_lines, had_tr)
    intervals = _kept_char_intervals(kept)

    disk_starts: list[int] = []
    disk_ends: list[int] = []
    for i, rl in enumerate(res_lines):
        c0 = starts[i]
        c1 = c0 + (len(rl) - 1) if rl else c0
        lo = _char_pos_to_disk(intervals, disk, c0)
        hi = _char_pos_to_disk(intervals, disk, c1)
        disk_starts.append(min(lo, hi))
        disk_ends.append(max(lo, hi))

    return NormalizedStorageText(
        raw_storage_text=raw_storage_text,
        strip_comments_text=strip_comments,
        llm_view=StorageLlmView(
            visible_for_llm=decoded,
            disk_line_start_1based=tuple(disk_starts),
            disk_line_end_1based=tuple(disk_ends),
        ),
    )


def format_kb_prompt_block(
    *,
    canonical_id: str,
    text: str,
    tags: list[str],
    include_comments: bool = False,
    strip_html: bool = False,
) -> str:
    """Format a KB object body for prompt display."""
    normalized = normalize_storage_text(text)
    body = text if include_comments else normalized.strip_comments_text
    if strip_html:
        body = strip_html_comments(body)
    header = f"KB[{canonical_id!r}]"
    if tags:
        header += f"  TAGS={', '.join(tags)}"
    body = body.rstrip("\n")
    if body:
        return f"{header}\n{body}\n"
    return f"{header}\n"


def format_kb_prompt_block_from_normalized(
    *,
    canonical_id: str,
    normalized: NormalizedStorageText,
    tags: list[str],
    include_comments: bool = False,
    strip_html: bool = False,
) -> str:
    """Format a KB prompt block from an already-normalized view."""
    body = (
        normalized.raw_storage_text
        if include_comments
        else normalized.strip_comments_text
    )
    if strip_html:
        body = strip_html_comments(body)
    header = f"KB[{canonical_id!r}]"
    if tags:
        header += f"  TAGS={', '.join(tags)}"
    body = body.rstrip("\n")
    if body:
        return f"{header}\n{body}\n"
    return f"{header}\n"


@dataclass(frozen=True)
class _PathCacheEntry:
    mtime_ns: int
    size: int
    normalized: NormalizedStorageText


class StorageTextNormalizer:
    """Per-storage cache of normalized views by file path and source id."""

    def __init__(self) -> None:
        self._path_cache: dict[Path, _PathCacheEntry] = {}
        self._source_cache: dict[str, NormalizedStorageText] = {}

    def normalize_path(self, path: Path) -> NormalizedStorageText:
        try:
            st = path.stat()
        except OSError as e:
            raise StorageNormalizationError(f"cannot stat file: {path}") from e
        cached = self._path_cache.get(path)
        if cached and cached.mtime_ns == st.st_mtime_ns and cached.size == st.st_size:
            return cached.normalized
        raw = path.read_text(encoding="utf-8")
        normalized = normalize_storage_text(raw)
        self._path_cache[path] = _PathCacheEntry(
            mtime_ns=st.st_mtime_ns, size=st.st_size, normalized=normalized
        )
        return normalized

    def normalize_raw(
        self, raw_storage_text: str, *, source_id: str | None = None
    ) -> NormalizedStorageText:
        if source_id is not None:
            cached = self._source_cache.get(source_id)
            if cached and cached.raw_storage_text == raw_storage_text:
                return cached
        normalized = normalize_storage_text(raw_storage_text)
        if source_id is not None:
            self._source_cache[source_id] = normalized
        return normalized

    def invalidate_path(self, path: Path) -> None:
        self._path_cache.pop(path, None)

    def invalidate_source(self, source_id: str) -> None:
        self._source_cache.pop(source_id, None)

