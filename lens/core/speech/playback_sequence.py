"""Visual-novel playback ordering: TTS-aligned text chunks interleaved with standalone image lines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from lens.core.narrative import NarrativeNode
from lens.core.project import get_mount_backend
from lens.core.annotations import iter_kept_storage_lines, parse_annotations, strip_html_comments
from lens.core.commands.attach import COMPOSITE_BG_CLASS, COMPOSITE_CLASS, COMPOSITE_FG_CLASS
from lens.core.speech.chunks import (
    is_eligible_tts_line,
    iter_raw_storage_text,
    strip_fenced_code_blocks,
    tts_cache_mount_prefix,
    tts_chunks_for_eligible_trimmed_line,
)
from lens.core.speech.tts_cache_sync import node_uses_tts_cache

_STANDALONE_IMAGE_LINE_RE = re.compile(
    r"^\s*!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)\s*$",
)

# Must match ``lens.core.commands.attach.build_embed`` for video (single-line, double-quoted src).
_ATTACH_VIDEO_LINE_RE = re.compile(
    r'^\s*<video\s+src="/mount/file/(?P<rel>[^"]+)"[^>]*>\s*</video>\s*$',
    re.IGNORECASE,
)

# Must match ``lens.core.commands.attach.build_layered_embed``.
_ATTACH_COMPOSITE_LINE_RE = re.compile(
    r'^\s*<div class="' + re.escape(COMPOSITE_CLASS) + r'">'
    r'<img src="/mount/file/(?P<bg>[^"]+)" alt="(?P<bg_alt>[^"]*)" class="' + re.escape(COMPOSITE_BG_CLASS) + r'">'
    r'<img src="/mount/file/(?P<fg>[^"]+)" alt="(?P<fg_alt>[^"]*)" class="' + re.escape(COMPOSITE_FG_CLASS) + r'">'
    r"</div>\s*$",
    re.IGNORECASE,
)


def parse_standalone_image_line(line: str) -> tuple[str, str] | None:
    """If *line* is only ``![alt](url)``, return ``(alt, url)`` else ``None``."""
    m = _STANDALONE_IMAGE_LINE_RE.match(line)
    if m is None:
        return None
    return (m.group("alt"), m.group("url").strip())


def parse_attach_video_line(line: str) -> tuple[str, str] | None:
    """If *line* is only the attach HTML video embed, return ``(alt_basename, mount_relative_url)``."""
    m = _ATTACH_VIDEO_LINE_RE.match(line)
    if m is None:
        return None
    rel = unquote(m.group("rel").lstrip("/"))
    alt = Path(rel).name
    return (alt, rel)


def parse_composite_line(line: str) -> tuple[str, str, str, str] | None:
    """If *line* is only the attach composite embed, return ``(bg_url, bg_alt, fg_url, fg_alt)``."""
    m = _ATTACH_COMPOSITE_LINE_RE.match(line)
    if m is None:
        return None
    bg = unquote(m.group("bg").lstrip("/"))
    fg = unquote(m.group("fg").lstrip("/"))
    bg_alt = unescape(m.group("bg_alt"))
    fg_alt = unescape(m.group("fg_alt"))
    return (bg, bg_alt, fg, fg_alt)


@dataclass(frozen=True, slots=True)
class PlaybackTextItem:
    type: Literal["text"]
    id: str
    line: int
    text: str
    ai_gen: bool
    tts_cached: bool | None
    """``True``/``False`` when the node uses TTS cache; ``None`` when TTS is not enabled."""


@dataclass(frozen=True, slots=True)
class PlaybackImageItem:
    type: Literal["image"]
    line: int
    alt: str
    url: str


@dataclass(frozen=True, slots=True)
class PlaybackVideoItem:
    type: Literal["video"]
    line: int
    alt: str
    url: str


@dataclass(frozen=True, slots=True)
class PlaybackLayeredItem:
    """Background+foreground composite scene (see ``attach.build_layered_embed``)."""

    type: Literal["layered"]
    line: int
    bg_url: str
    bg_alt: str
    fg_url: str
    fg_alt: str


PlaybackItem = PlaybackTextItem | PlaybackImageItem | PlaybackVideoItem | PlaybackLayeredItem


def _tts_cached_chunk_ids(node: NarrativeNode, project_root: Path) -> frozenset[str] | None:
    """Chunk ids that have ``.mp3`` under this node's cache prefix, or ``None`` if TTS cache is off."""
    if not node_uses_tts_cache(node):
        return None
    backend = get_mount_backend(project_root)
    if backend is None:
        return frozenset()
    entries = backend.list_dir(tts_cache_mount_prefix(node))
    if not entries:
        return frozenset()
    out: set[str] = set()
    for e in entries:
        if e.get("is_dir"):
            continue
        name = e.get("name", "")
        if not isinstance(name, str):
            continue
        lower = name.lower()
        if lower.endswith(".mp3"):
            out.add(name[: -len(".mp3")])
    return frozenset(out)


def _ai_gen_mask_by_disk_line(cleaned_storage_text: str) -> list[bool]:
    """1-based mask: True for physical lines inside operator blocks.

    The mask is defined on the "cleaned" buffer (HTML comments and fenced code blocks
    emptied with line count preserved), so its indices line up 1:1 with raw on-disk
    line numbers.
    """
    n = len(cleaned_storage_text.split("\n"))
    mask = [False] * (n + 1)  # index 0 unused

    anns = parse_annotations(cleaned_storage_text)
    stack: list[tuple[str, str | None, int]] = []
    for ann in anns:
        key = (ann.operator, ann.id)
        if ann.self_closing:
            continue
        if not ann.closing:
            stack.append((key[0], key[1], ann.line_end + 1))
            continue

        # Close: match the most recent compatible opener (nesting-safe).
        for i in range(len(stack) - 1, -1, -1):
            op, op_id, start = stack[i]
            if (op, op_id) != key:
                continue
            stack.pop(i)
            end = ann.line_start - 1
            if start <= end:
                for ln in range(max(1, start), min(n, end) + 1):
                    mask[ln] = True
            break

    # Unterminated operator block (common at cursor): mark to EOF.
    for _op, _op_id, start in stack:
        if start <= n:
            for ln in range(max(1, start), n + 1):
                mask[ln] = True

    return mask


def playback_items_for_node(node: NarrativeNode, project_root: Path) -> list[PlaybackItem]:
    """Ordered playback items: standalone image lines and TTS-eligible prose chunks.

    Each item's ``line`` is the 1-based raw on-disk line number, matching attach,
    the UI line picker, and ``NarrativeAddress @N``.
    """
    raw = iter_raw_storage_text(node)
    cleaned = strip_fenced_code_blocks(strip_html_comments(raw))
    ai_gen_mask = _ai_gen_mask_by_disk_line(cleaned)
    kept = iter_kept_storage_lines(cleaned)
    cached_ids = _tts_cached_chunk_ids(node, project_root)

    out: list[PlaybackItem] = []
    for line, disk in kept:
        composite = parse_composite_line(line)
        if composite is not None:
            bg_url, bg_alt, fg_url, fg_alt = composite
            out.append(
                PlaybackLayeredItem(
                    type="layered", line=disk, bg_url=bg_url, bg_alt=bg_alt, fg_url=fg_url, fg_alt=fg_alt
                )
            )
            continue
        img = parse_standalone_image_line(line)
        if img is not None:
            alt, url = img
            out.append(PlaybackImageItem(type="image", line=disk, alt=alt, url=url))
            continue
        vid = parse_attach_video_line(line)
        if vid is not None:
            alt_v, url_v = vid
            out.append(PlaybackVideoItem(type="video", line=disk, alt=alt_v, url=url_v))
            continue
        if not is_eligible_tts_line(line):
            continue
        trimmed = line.strip()
        for ch in tts_chunks_for_eligible_trimmed_line(trimmed, disk):
            cached = None if cached_ids is None else (ch.id in cached_ids)
            out.append(
                PlaybackTextItem(
                    type="text",
                    id=ch.id,
                    line=ch.source_kept_line_1,
                    text=ch.raw_line,
                    ai_gen=ai_gen_mask[disk] if 0 < disk < len(ai_gen_mask) else False,
                    tts_cached=cached,
                )
            )
    return out
