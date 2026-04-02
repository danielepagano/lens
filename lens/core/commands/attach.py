"""Core implementation of the attach command."""

from __future__ import annotations

from pathlib import Path

from lens.core.address import NarrativeAddress
from lens.core.annotations import find_front_matter_span, parse_annotations
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, get_mount_backend, resolve_address

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".mp4", ".webm", ".mov", ".avi",
    ".pdf", ".txt", ".md",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".avi"}
DOCUMENT_EXTS = {".pdf", ".txt", ".md"}
# Markdown/text files open in the in-app preview viewer instead of raw download
PREVIEW_EXTS = {".md", ".txt"}


def media_type(ext: str) -> str:
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return "document"


def build_embed(relative_path: str, ext: str) -> str:
    path = relative_path.lstrip("/")
    fname = Path(relative_path).name
    if ext in IMAGE_EXTS:
        return f"![{fname}](/mount/file/{path})"
    if ext in VIDEO_EXTS:
        return f'<video src="/mount/file/{path}" controls style="max-width:100%"></video>'
    if ext in PREVIEW_EXTS:
        return f"[{fname}](/mount/preview/{path})"
    return f"[{fname}](/mount/file/{path})"


def _trailing_empty_line_count(lines: list[str]) -> int:
    n = 0
    for i in range(len(lines) - 1, -1, -1):
        if lines[i] == "":
            n += 1
        else:
            break
    return n


def _leading_empty_line_count(lines: list[str]) -> int:
    n = 0
    for line in lines:
        if line == "":
            n += 1
        else:
            break
    return n


def _join_with_embed(prefix_lines: list[str], embed: str, suffix_lines: list[str]) -> str:
    left = "\n".join(prefix_lines)
    right = "\n".join(suffix_lines) if suffix_lines else ""

    if prefix_lines:
        t = _trailing_empty_line_count(prefix_lines)
        sep_before = "\n" if t >= 1 else "\n\n"
        chunk_left = left + sep_before + embed
    else:
        chunk_left = embed

    if not suffix_lines:
        return chunk_left + "\n"

    lead = _leading_empty_line_count(suffix_lines)
    sep_after = "\n" if lead >= 1 else "\n\n"
    return chunk_left + sep_after + right


def validate_attach_insertion_point(text: str, line: int) -> None:
    """Reject *line* (1-based) if in front matter or strictly inside a multiline tag."""
    lines = text.split("\n")
    total = len(lines)
    if line < 1 or line > total:
        raise LensException(
            f"line {line} is out of range for this node (1\u2013{total})"
        )

    fm = find_front_matter_span(text)
    if fm is not None:
        fm_first = fm[0] + 1
        fm_last = fm[1]
        if fm_first <= line <= fm_last:
            raise LensException("cannot attach in front matter")

    for ann in parse_annotations(text):
        if ann.line_start <= line < ann.line_end:
            raise LensException(
                "cannot attach inside an annotation tag (use a line on or after the closing `]: #`)"
            )


def insert_embed_after_line(content: str, line: int, embed: str) -> str:
    """Insert *embed* after 1-based *line*, with minimal blank-line padding."""
    lines = content.split("\n")
    validate_attach_insertion_point(content, line)
    prefix = lines[:line]
    suffix = lines[line:]
    return _join_with_embed(prefix, embed, suffix)


def _resolve_attach_target(session: ProjectSession, address: str | None) -> NarrativeNode:
    narrative = session.active_narrative
    if narrative is None:
        raise LensException("no active narrative (run 'lens use <slug>' first)")

    try:
        addr = NarrativeAddress.parse(address or "/@cursor")
    except ValueError as e:
        raise LensException(f"invalid address: {e}") from e

    try:
        resolved = resolve_address(addr.node_only(), session.project_root)
        target = resolved.to_node(session.project_root)
    except (ValueError, FileNotFoundError) as e:
        raise LensException(str(e)) from e

    if not target.exists():
        raise LensException(f"node does not exist: {address or '/@cursor'}")
    return target


def attach(
    session: ProjectSession,
    relative_path: str,
    *,
    preview: bool = False,
    address: str | None = None,
    line: int | None = None,
) -> dict[str, str]:
    """Validate a mount-relative file path and optionally insert its embed after *line* in *address*.

    When *address* is omitted, uses ``/@cursor``. When *line* is omitted, appends after the last line.

    Returns a dict with keys: path, type, ext (preview mode) or path, type, embed (insert mode).
    Raises LensException for configuration or validation errors.
    """
    backend = get_mount_backend(session.project_root)
    if backend is None:
        raise LensException("no mount_point configured in lens.toml")

    ext = Path(relative_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise LensException(
            f"unsupported extension '{ext}' — supported: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )

    try:
        exists = backend.file_exists(relative_path)
    except ValueError as e:
        raise LensException(str(e))
    if not exists:
        hint = ""
        if relative_path.startswith("/") or relative_path.startswith("knowledge/") or relative_path.startswith("narrative/"):
            hint = " (path must be relative to the mount point, not the filesystem or project)"
        raise LensException(f"file not found in mount: {relative_path}{hint}")

    mtype = media_type(ext)
    if preview:
        return {"path": relative_path, "type": mtype, "ext": ext}

    target = _resolve_attach_target(session, address)
    node_path = target.md_path()
    content = node_path.read_text()
    embed = build_embed(relative_path, ext)
    lines = content.split("\n")
    insert_line = len(lines) if line is None else line
    if line is not None:
        new_text = insert_embed_after_line(content, insert_line, embed)
    else:
        new_text = _join_with_embed(lines, embed, [])

    storage = session.new_storage(owner=None)
    storage.write_file(node_path, new_text)
    return {"path": relative_path, "type": mtype, "embed": embed}
