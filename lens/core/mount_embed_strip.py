"""Detect and strip Lens mount attachment embeds from LLM-visible text.

``lens.core.commands.attach.build_embed``/``build_layered_embed`` insert markdown
image/links, a single-line HTML ``<video>``, or a single-line HTML composite
(background+foreground) ``<div>`` that reference ``/mount/file/`` or
``/mount/preview``. Those lines are stripped from prompts so models do not
imitate bogus media URLs.
"""

from __future__ import annotations

import re

# Mirrors ``attach.build_embed`` + ``speech.playback_sequence._ATTACH_VIDEO_LINE_RE``.
_STANDALONE_MOUNT_IMAGE_MD = re.compile(
    r"^\s*!\[[^\]]*\]\(/mount/file/[^)]+\)\s*$",
)
_STANDALONE_MOUNT_LINK_MD = re.compile(
    r"^\s*\[[^\]]*\]\(/mount/(?:file|preview)/[^)]+\)\s*$",
)
_ATTACH_VIDEO_FULL_LINE_RE = re.compile(
    r'^\s*<video\s+src="/mount/file/[^"]+"[^>]*>\s*</video>\s*$',
    re.IGNORECASE,
)
# Mirrors ``attach.build_layered_embed`` / ``speech.playback_sequence._ATTACH_COMPOSITE_LINE_RE``.
_ATTACH_COMPOSITE_FULL_LINE_RE = re.compile(
    r'^\s*<div class="lens-vn-composite">'
    r'<img src="/mount/file/[^"]+" alt="[^"]*" class="lens-vn-bg">'
    r'<img src="/mount/file/[^"]+" alt="[^"]*" class="lens-vn-fg">'
    r"</div>\s*$",
    re.IGNORECASE,
)


def line_is_standalone_lens_mount_attachment(line: str) -> bool:
    """True when *line* is only an attach-style mount embed (own line)."""
    if not line.strip():
        return False
    s = line.strip()
    return bool(
        _STANDALONE_MOUNT_IMAGE_MD.match(s)
        or _STANDALONE_MOUNT_LINK_MD.match(s)
        or _ATTACH_VIDEO_FULL_LINE_RE.match(s)
        or _ATTACH_COMPOSITE_FULL_LINE_RE.match(s)
    )


def strip_standalone_lens_mount_attachment_lines(text: str) -> str:
    """Remove lines that consist solely of attach-style mount embeds."""
    if not text or "/mount/" not in text:
        return text
    lines = text.split("\n")
    kept = [
        ln for ln in lines if not line_is_standalone_lens_mount_attachment(ln)
    ]
    return "\n".join(kept)
