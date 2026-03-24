"""Core implementation of the attach command."""

from __future__ import annotations

from pathlib import Path

from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, get_mount_backend

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


def attach(
    session: ProjectSession,
    relative_path: str,
    *,
    preview: bool = False,
) -> dict[str, str]:
    """Validate a mount-relative file path and optionally insert its embed at cursor.

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
        raise LensException(f"file not found: {relative_path}")

    mtype = media_type(ext)
    if preview:
        return {"path": relative_path, "type": mtype, "ext": ext}

    narrative = session.active_narrative
    if narrative is None:
        raise LensException("no active narrative")

    cursor_node = narrative.find_cursor()
    node_path = cursor_node.md_path()
    content = node_path.read_text()
    embed = build_embed(relative_path, ext)
    storage = session.new_storage(owner=None)
    storage.write_file(node_path, content.rstrip("\n") + "\n\n" + embed + "\n")
    return {"path": relative_path, "type": mtype, "embed": embed}
