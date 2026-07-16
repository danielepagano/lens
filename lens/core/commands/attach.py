"""Core implementation of the attach command."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from lens.core.address import NarrativeAddress
from lens.core.annotations import find_front_matter_span, parse_annotations
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, get_mount_backend, resolve_address
from lens.core.storage import Storage

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
    url_path = quote(path, safe="/")
    if ext in IMAGE_EXTS:
        return f"![{fname}](/mount/file/{url_path})"
    if ext in VIDEO_EXTS:
        return (
            f'<video src="/mount/file/{url_path}" controls playsinline webkit-playsinline '
            f'preload="metadata" style="max-width:100%"></video>'
        )
    if ext in PREVIEW_EXTS:
        return f"[{fname}](/mount/preview/{url_path})"
    return f"[{fname}](/mount/file/{url_path})"


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
    """Reject 1-based insertion *line* that would split front matter or a multi-line tag.

    The position is the gap *before* raw on-disk line ``line``. Allowed range is
    ``1 .. len(lines) + 1`` (where ``len(lines) + 1`` means "append after the last line").
    """
    lines = text.split("\n")
    total = len(lines)
    if line < 1 or line > total + 1:
        raise LensException(
            f"line {line} is out of range for this node (1\u2013{total + 1})"
        )

    fm = find_front_matter_span(text)
    if fm is not None and line <= fm[1]:
        raise LensException("cannot attach in front matter")

    for ann in parse_annotations(text):
        if ann.line_start < line <= ann.line_end:
            raise LensException(
                "cannot attach inside an annotation tag (use a line on or after the closing `]: #`)"
            )


def insert_embed_at_line(content: str, line: int, embed: str) -> str:
    """Insert *embed* at 1-based raw on-disk *line*, pushing existing content down.

    ``line == len(lines) + 1`` appends after the last line. Padding blank lines are
    inserted as needed to keep the surrounding markdown sane.
    """
    lines = content.split("\n")
    validate_attach_insertion_point(content, line)
    prefix = lines[: line - 1]
    suffix = lines[line - 1 :]
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
    if line is not None:
        new_text = insert_embed_at_line(content, line, embed)
    else:
        new_text = _join_with_embed(content.split("\n"), embed, [])

    storage = session.new_storage(owner=None)
    storage.write_file(node_path, new_text)
    return {"path": relative_path, "type": mtype, "embed": embed}


# ---------------------------------------------------------------------------
# Media reference update on move/rename
# ---------------------------------------------------------------------------


def _mount_ref_search_variants(old_path: str) -> list[str]:
    """Return the raw and URL-encoded forms of *old_path* that may appear in embed URLs."""
    stripped = old_path.lstrip("/")
    encoded = quote(stripped, safe="/")
    variants = [stripped]
    if encoded != stripped:
        variants.append(encoded)
    return variants


def _scan_md_files(project_root: Path) -> list[Path]:
    """Collect all ``.md`` files under ``narrative/`` and ``knowledge/`` in *project_root*."""
    dirs = [project_root / "narrative", project_root / "knowledge"]
    result: list[Path] = []
    for d in dirs:
        if d.is_dir():
            result.extend(d.rglob("*.md"))
    return result


def find_files_with_mount_refs(project_root: Path, old_path: str) -> list[Path]:
    """Return ``.md`` files that reference *old_path* in a mount embed URL.

    Scans ``narrative/`` and ``knowledge/`` directories.  Matches both raw and
    URL-encoded path forms.  Read-only — does not modify any files.
    """
    variants = _mount_ref_search_variants(old_path)
    hits: list[Path] = []
    for md_path in _scan_md_files(project_root):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(variant in text for variant in variants):
            hits.append(md_path)
    return hits


def update_media_references(
    project_root: Path, old_path: str, new_path: str
) -> int:
    """Replace mount embed references from *old_path* to *new_path* in project files.

    Walks ``narrative/`` and ``knowledge/`` directories and rewrites any
    ``.md`` file that embeds *old_path* via ``/mount/file/`` or
    ``/mount/preview/``.

    Returns the number of files that were updated.
    """
    old_variants = _mount_ref_search_variants(old_path)
    new_stripped = new_path.lstrip("/")
    new_encoded = quote(new_stripped, safe="/")

    storage = Storage(project_root, owner=None)
    updated = 0

    for md_path in _scan_md_files(project_root):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue

        new_text = text
        for old_variant in old_variants:
            # Build the replacement: map each old variant to the matching new form.
            # Raw old → raw new; URL-encoded old → URL-encoded new.
            if old_variant == old_path.lstrip("/"):
                replacement = new_stripped
            else:
                replacement = new_encoded
            new_text = new_text.replace(old_variant, replacement)

        if new_text != text:
            storage.write_file(md_path, new_text)
            updated += 1

    return updated
