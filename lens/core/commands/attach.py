"""Core implementation of the attach command."""

from __future__ import annotations

from html import escape
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


# Composite (background + foreground) attachment: single-line HTML so it round-trips through
# markdown editors intact and renders sensibly in plain (non-VN) reading mode. VN playback
# parses it back out via ``lens.core.speech.playback_sequence.parse_composite_line`` — the
# attribute order/quoting here must match that regex (and its TS mirror in ``mountEmbed.ts``).
COMPOSITE_CLASS = "lens-vn-composite"
COMPOSITE_BG_CLASS = "lens-vn-bg"
COMPOSITE_FG_CLASS = "lens-vn-fg"


def build_layered_embed(bg_relative_path: str, fg_relative_path: str) -> str:
    """Build the single-line HTML embed for a background+foreground composite attachment."""
    bg_path = bg_relative_path.lstrip("/")
    fg_path = fg_relative_path.lstrip("/")
    bg_name = escape(Path(bg_relative_path).name, quote=True)
    fg_name = escape(Path(fg_relative_path).name, quote=True)
    bg_url = quote(bg_path, safe="/")
    fg_url = quote(fg_path, safe="/")
    return (
        f'<div class="{COMPOSITE_CLASS}">'
        f'<img src="/mount/file/{bg_url}" alt="{bg_name}" class="{COMPOSITE_BG_CLASS}">'
        f'<img src="/mount/file/{fg_url}" alt="{fg_name}" class="{COMPOSITE_FG_CLASS}">'
        f"</div>"
    )


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


def attach_layered(
    session: ProjectSession,
    bg_relative_path: str,
    fg_relative_path: str,
    *,
    address: str | None = None,
    line: int | None = None,
) -> dict[str, str]:
    """Attach a background+foreground composite image pair as a single embed.

    Both paths must resolve to supported image extensions and exist on the mount.
    See :func:`build_layered_embed` for the emitted markup and
    ``lens.core.speech.playback_sequence`` for how VN playback parses it back out.
    """
    backend = get_mount_backend(session.project_root)
    if backend is None:
        raise LensException("no mount_point configured in lens.toml")

    for rel in (bg_relative_path, fg_relative_path):
        ext = Path(rel).suffix.lower()
        if ext not in IMAGE_EXTS:
            raise LensException(
                f"layered attach requires images — '{rel}' has unsupported extension '{ext}'"
            )
        try:
            exists = backend.file_exists(rel)
        except ValueError as e:
            raise LensException(str(e))
        if not exists:
            raise LensException(f"file not found in mount: {rel}")

    target = _resolve_attach_target(session, address)
    node_path = target.md_path()
    content = node_path.read_text()
    embed = build_layered_embed(bg_relative_path, fg_relative_path)
    if line is not None:
        new_text = insert_embed_at_line(content, line, embed)
    else:
        new_text = _join_with_embed(content.split("\n"), embed, [])

    storage = session.new_storage(owner=None)
    storage.write_file(node_path, new_text)
    return {
        "bg_path": bg_relative_path,
        "fg_path": fg_relative_path,
        "type": "image",
        "embed": embed,
    }


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


def get_mount_ref_line_numbers(
    project_root: Path, old_path: str
) -> dict[str, list[int]]:
    """Return ``{file_path: [line_numbers]}`` for all references to *old_path*.

    Scans ``narrative/`` and ``knowledge/`` directories.  Line numbers are 1-based.
    """

    variants = _mount_ref_search_variants(old_path)
    result: dict[str, list[int]] = {}
    for md_path in _scan_md_files(project_root):
        try:
            lines = md_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        hits = [
            i for i, line in enumerate(lines, start=1)
            if any(variant in line for variant in variants)
        ]
        if hits:
            result[str(md_path.relative_to(project_root))] = hits
    return result


def remove_media_references(project_root: Path, old_path: str) -> int:
    """Remove mount embed references to *old_path* from project files.

    For standalone embed lines (the normal case), the entire line plus its
    trailing blank line is deleted to avoid double-blanks.  For inline
    (non-standalone) embeds, only the URL portion is removed via plain
    string replacement.

    Returns the number of files that were modified.
    """
    from lens.core.mount_embed_strip import line_is_standalone_lens_mount_attachment

    old_variants = _mount_ref_search_variants(old_path)
    storage = Storage(project_root, owner=None)
    updated = 0

    for md_path in _scan_md_files(project_root):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue

        lines = text.split("\n")
        new_lines: list[str] = []
        i = 0
        changed = False
        while i < len(lines):
            line = lines[i]
            has_ref = any(variant in line for variant in old_variants)
            if not has_ref:
                new_lines.append(line)
                i += 1
                continue

            changed = True
            if line_is_standalone_lens_mount_attachment(line):
                # Remove the embed line.
                i += 1
            else:
                # Inline embed: remove only the URL portions
                inline_cleaned = line
                for variant in old_variants:
                    inline_cleaned = inline_cleaned.replace(variant, "")
                new_lines.append(inline_cleaned)
                i += 1

        if changed:
            # Collapse runs of 3+ blank lines down to 2 (one visual blank).
            result_lines: list[str] = []
            blank_run = 0
            for ln in new_lines:
                if ln == "":
                    blank_run += 1
                    if blank_run <= 1:
                        result_lines.append(ln)
                else:
                    blank_run = 0
                    result_lines.append(ln)
            storage.write_file(md_path, "\n".join(result_lines))
            updated += 1

    return updated


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
