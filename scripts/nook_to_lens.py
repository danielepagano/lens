#!/usr/bin/env python3
"""
Migrate a Nook world to a Lens project.

Resolves the SQLite DB and optional media root from a Nook layout:
  - Nook ``dat/`` directory + ``--world <slug>`` → ``dat/worlds/<slug>/`` (``<slug>.db``, ``<slug>.toml``)
  - World folder directly: ``.../dat/worlds/<slug>`` (same files inside)
  - Legacy: path to a ``*.db`` file (optional sibling ``*.toml`` for ``media_path``)

Creates a Lens project in the output folder (no git init). Does not copy media files: when
the world has ``media_path``, ``[project] mount_point`` is set to that same directory (absolute
path) and scene embeds use paths relative to it.

Usage:
    python scripts/nook_to_lens.py /path/to/nook/dat --world myworld /path/to/lens-out
    python scripts/nook_to_lens.py /path/to/nook/dat/worlds/myworld /path/to/lens-out
    python scripts/nook_to_lens.py /path/to/world.db /path/to/lens-out
"""

from __future__ import annotations

import argparse
import io
import re
import sqlite3
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Repo root: import lens + tomli_w
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import tomli_w  # noqa: E402

from lens.core.commands.attach import SUPPORTED_EXTENSIONS, build_embed  # noqa: E402

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALUE_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class NookPaths:
    db_path: Path
    """World SQLite database."""

    media_root: Path | None
    """Nook ``media_path`` from world config, if set and existing."""


def _read_world_toml_config(toml_path: Path) -> dict[str, object]:
    if not toml_path.is_file():
        return {}
    with toml_path.open("rb") as f:
        data = tomllib.load(f)
    raw = data.get("config")
    return dict(raw) if isinstance(raw, dict) else {}


def _resolve_db_from_world_dir(world_dir: Path, slug: str) -> Path:
    cfg = _read_world_toml_config(world_dir / f"{slug}.toml")
    raw = cfg.get("db_path")
    if isinstance(raw, str) and raw.strip():
        db = Path(raw).expanduser()
        if not db.is_absolute():
            db = (world_dir / db).resolve()
        return db
    return (world_dir / f"{slug}.db").resolve()


def _media_path_from_config(world_dir: Path, slug: str) -> Path | None:
    cfg = _read_world_toml_config(world_dir / f"{slug}.toml")
    raw = cfg.get("media_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    root = Path(raw).expanduser().resolve()
    if root.is_dir():
        return root
    return None


def resolve_nook_paths(nook_input: Path, world: str | None) -> NookPaths:
    """Resolve DB path and Nook media root from dat dir, world dir, or legacy .db path."""
    p = nook_input.resolve()
    if p.is_file():
        if p.suffix.lower() != ".db":
            msg = f"Expected a .db file or a directory, got file: {p}"
            raise ValueError(msg)
        slug = p.stem
        world_dir = p.parent
        cfg_media = _media_path_from_config(world_dir, slug)
        return NookPaths(db_path=p, media_root=cfg_media)

    if not p.is_dir():
        msg = f"Not found or not a directory: {p}"
        raise ValueError(msg)

    if (p / "worlds").is_dir():
        if not world or not _SLUG_PATTERN.fullmatch(world):
            msg = "When pointing at Nook dat/, pass --world <slug> (alphanumeric, _ or - only)."
            raise ValueError(msg)
        world_dir = (p / "worlds" / world).resolve()
        if not world_dir.is_dir():
            msg = f"World directory not found: {world_dir}"
            raise ValueError(msg)
        db = _resolve_db_from_world_dir(world_dir, world)
        media = _media_path_from_config(world_dir, world)
        return NookPaths(db_path=db, media_root=media)

    # Treat as a single world's folder (e.g. dat/worlds/myworld)
    slug = p.name
    if not _SLUG_PATTERN.fullmatch(slug):
        msg = (
            f"World folder name must be a valid slug: {slug!r}. "
            "Or pass the Nook dat/ directory with --world <slug>."
        )
        raise ValueError(msg)
    db = _resolve_db_from_world_dir(p, slug)
    media = _media_path_from_config(p, slug)
    return NookPaths(db_path=db, media_root=media)


def slugify(s: str, prefix: str = "") -> str:
    """Convert string to a valid slug (alphanumeric, underscores, hyphens)."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", s.strip()).strip("-").lower() or "untitled"
    if prefix:
        s = f"{prefix}-{s}"
    if _SLUG_PATTERN.fullmatch(s):
        return s
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", s)
    return safe[:64] if len(safe) > 64 else safe or "x"


def validate_tag(tag: str) -> bool:
    if not tag:
        return False
    if ":" in tag and "." in tag:
        return False
    if ":" in tag:
        parts = tag.split(":", 1)
        return len(parts) == 2 and all(_VALUE_PATTERN.fullmatch(p) for p in parts)
    if "." in tag:
        parts = tag.split(".", 1)
        return len(parts) == 2 and all(_VALUE_PATTERN.fullmatch(p) for p in parts)
    return bool(_VALUE_PATTERN.fullmatch(tag))


def migrate_knowledge(conn: sqlite3.Connection, root: Path) -> None:
    """Migrate kb_objects and kb_tags to Lens knowledge store."""
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('kb_objects', 'kb_tags')"
    )
    tables = {row[0] for row in cursor.fetchall()}
    if "kb_objects" not in tables:
        return

    cursor.execute("SELECT id, type, key, text FROM kb_objects")
    rows = cursor.fetchall()

    kb_tags: dict[int, list[str]] = {}
    if "kb_tags" in tables:
        cursor.execute("SELECT object_id, tag FROM kb_tags")
        for row in cursor.fetchall():
            oid, tag = row[0], row[1]
            if validate_tag(tag):
                kb_tags.setdefault(oid, []).append(tag)

    knowledge_dir = root / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    tag_to_objs: dict[str, set[str]] = {}
    obj_to_tags: dict[str, set[str]] = {}

    for row in rows:
        oid, type_name, key, text = row[0], row[1], row[2], row[3]
        canonical_id = f"{type_name}.{key}"
        type_dir = knowledge_dir / type_name
        type_dir.mkdir(exist_ok=True)
        path = type_dir / f"{key}.md"
        path.write_text(text or "", encoding="utf-8")

        tags = kb_tags.get(oid, [])
        for tag in tags:
            tag_to_objs.setdefault(tag, set()).add(canonical_id)
            obj_to_tags.setdefault(canonical_id, set()).add(tag)

    tags_path = knowledge_dir / "tags.toml"
    payload: dict[str, object] = {}
    if tag_to_objs:
        payload["tags"] = {k: sorted(v) for k, v in tag_to_objs.items()}
    if obj_to_tags:
        payload["objects"] = {k: sorted(v) for k, v in obj_to_tags.items()}
    if payload:
        buf = io.BytesIO()
        tomli_w.dump(payload, buf)
        tags_path.write_bytes(buf.getvalue())


def _get_pins(conn: sqlite3.Connection, scope_type: str, scope_id: int) -> list[str]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT knowledge_id FROM pin WHERE scope_type = ? AND scope_id = ? ORDER BY created_at",
        (scope_type, scope_id),
    )
    return [row[0] for row in cursor.fetchall()]


def _render_front_matter(kb_pin: list[str]) -> str:
    if not kb_pin:
        return ""
    lines = ["[\n  kb_pin:"]
    for kid in sorted(kb_pin):
        lines.append(f"    - {kid}")
    lines.append("]: #\n\n")
    return "\n".join(lines)


def _find_nook_owner_media_dir(media_dir: Path, owner_object_id: str) -> Path | None:
    if "." in owner_object_id:
        _type_part, key_part = owner_object_id.split(".", 1)
        possible_folder_names = [owner_object_id, key_part]
    else:
        possible_folder_names = [owner_object_id]

    direct = media_dir / owner_object_id
    if direct.is_dir():
        return direct

    for folder_name in possible_folder_names:
        for actual_folder in media_dir.iterdir():
            if actual_folder.is_dir() and actual_folder.name.lower() == folder_name.lower():
                return actual_folder
    return None


def _resolve_nook_asset_file(
    media_root: Path,
    owner_object_id: str,
    sub_folder_path: str,
    file_name: str,
) -> Path | None:
    owner_dir = _find_nook_owner_media_dir(media_root, owner_object_id)
    if owner_dir is None:
        return None
    name = Path(file_name).name
    if sub_folder_path.strip():
        sub_path = sub_folder_path.strip().rstrip("/")
        candidate = (owner_dir / sub_path / name).resolve()
    else:
        candidate = (owner_dir / name).resolve()
    media_resolved = media_root.resolve()
    if not candidate.is_file():
        return None
    if media_resolved not in candidate.parents and candidate != media_resolved:
        return None
    return candidate


def _set_lens_mount_point(lens_toml: Path, mount_root: Path) -> None:
    """Point Lens ``mount_point`` at Nook's existing media directory (absolute path)."""
    resolved = str(mount_root.resolve())
    if lens_toml.exists():
        with lens_toml.open("rb") as f:
            data: dict[str, object] = tomllib.load(f)
    else:
        data = {}
    pr = data.get("project")
    project = dict(pr) if isinstance(pr, dict) else {}
    project["mount_point"] = resolved
    data["project"] = project
    buf = io.BytesIO()
    tomli_w.dump(data, buf)
    lens_toml.write_bytes(buf.getvalue())


def _chunk_media_embed(
    *,
    media_root: Path,
    asset_id: int,
    owner_object_id: str,
    sub_folder_path: str,
    file_name: str,
) -> str | None:
    src = _resolve_nook_asset_file(media_root, owner_object_id, sub_folder_path, file_name)
    if src is None:
        print(
            f"Warning: media asset {asset_id} ({owner_object_id}/{sub_folder_path}{file_name}) not found on disk",
            file=sys.stderr,
        )
        return None

    root = media_root.resolve()
    try:
        rel = src.resolve().relative_to(root)
    except ValueError:
        print(f"Warning: media file outside media_path, skipping asset {asset_id}", file=sys.stderr)
        return None

    mount_rel = rel.as_posix()
    ext = src.suffix.lower()
    if ext in SUPPORTED_EXTENSIONS:
        return build_embed(mount_rel, ext)
    label = src.name
    return f"[{label}](/mount/file/{mount_rel})"


def migrate_narrative(
    conn: sqlite3.Connection,
    root: Path,
    *,
    media_root: Path | None,
) -> None:
    """Migrate books/chapters/scenes to Lens narrative with sections."""
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('pin', 'media_asset', 'chunk')"
    )
    tables = {row[0] for row in cursor.fetchall()}
    has_pins = "pin" in tables
    has_chunk_media = "chunk" in tables and "media_asset" in tables

    cursor.execute("SELECT id, title FROM book ORDER BY created_at")
    books = cursor.fetchall()

    narrative_dir = root / "narrative"
    narrative_dir.mkdir(parents=True, exist_ok=True)

    for book_id, book_title in books:
        base = slugify(book_title) or "untitled"
        book_slug = f"book-{base}-{book_id}"[:80]
        book_path = narrative_dir / book_slug
        book_path.mkdir(exist_ok=True)

        cursor.execute(
            "SELECT id, number, title, summary_text, directions_text FROM chapter WHERE book_id = ? ORDER BY number",
            (book_id,),
        )
        chapters = cursor.fetchall()

        book_pins = _get_pins(conn, "book", book_id) if has_pins else []
        root_lines: list[str] = [_render_front_matter(book_pins), f"# {book_title}", ""]
        section_blocks: list[str] = []

        for ch_id, ch_num, ch_title, ch_summary, ch_directions in chapters:
            ch_slug = f"ch-{ch_num}"
            ch_dir = book_path / ch_slug
            ch_dir.mkdir(exist_ok=True)

            ch_pins = _get_pins(conn, "chapter", ch_id) if has_pins else []
            ch_content_lines: list[str] = [_render_front_matter(ch_pins), f"# {ch_title}", ""]
            if ch_directions and ch_directions.strip():
                ch_content_lines.append(ch_directions.strip())
                ch_content_lines.append("")

            cursor.execute(
                "SELECT id, number, summary_text FROM scene WHERE chapter_id = ? ORDER BY number",
                (ch_id,),
            )
            scenes = cursor.fetchall()

            scene_blocks: list[str] = []
            for scene_id, scene_num, scene_summary in scenes:
                scene_slug = f"scene-{scene_num}"
                scene_dir = ch_dir / scene_slug
                scene_dir.mkdir(exist_ok=True)

                if has_chunk_media and media_root is not None:
                    cursor.execute(
                        """SELECT c.text, c.show_media_asset_id FROM chunk c
                           JOIN request r ON c.request_id = r.id
                           WHERE r.scene_id = ? ORDER BY r.order_in_scene, c.order_in_request""",
                        (scene_id,),
                    )
                    chunk_rows = cursor.fetchall()
                    parts: list[str] = []
                    for text, media_id in chunk_rows:
                        t = (text or "").strip()
                        if t:
                            parts.append(t)
                        if media_id is not None:
                            cursor.execute(
                                """SELECT id, owner_object_id, file_name, sub_folder_path
                                   FROM media_asset WHERE id = ?""",
                                (media_id,),
                            )
                            row = cursor.fetchone()
                            if row is None:
                                print(
                                    f"Warning: chunk references missing media_asset id={media_id}",
                                    file=sys.stderr,
                                )
                                continue
                            _aid, owner_oid, fname, subfolder = row[0], row[1], row[2], row[3]
                            embed = _chunk_media_embed(
                                media_root=media_root,
                                asset_id=int(_aid),
                                owner_object_id=str(owner_oid),
                                sub_folder_path=str(subfolder or ""),
                                file_name=str(fname),
                            )
                            if embed:
                                parts.append(embed)
                    scene_prose = "\n\n".join(parts).strip() if parts else ""
                else:
                    cursor.execute(
                        """SELECT c.text FROM chunk c
                           JOIN request r ON c.request_id = r.id
                           WHERE r.scene_id = ? ORDER BY r.order_in_scene, c.order_in_request""",
                        (scene_id,),
                    )
                    chunks = [row[0] for row in cursor.fetchall()]
                    scene_prose = "\n\n".join(chunks).strip() if chunks else ""

                scene_pins = _get_pins(conn, "scene", scene_id) if has_pins else []
                scene_content = _render_front_matter(scene_pins) + (scene_prose or "")
                scene_path = scene_dir / "_node.md"
                scene_path.write_text(scene_content, encoding="utf-8")

                summary = (scene_summary or "").strip()
                scene_blocks.append(
                    f"[section:{scene_slug}]: #\n\n{summary}\n\n[/section:{scene_slug}]: #"
                )

            ch_content = "\n\n".join(ch_content_lines).rstrip()
            ch_content += "\n\n" + "\n\n".join(scene_blocks)
            (ch_dir / "_node.md").write_text(ch_content, encoding="utf-8")

            ch_summary = (ch_summary or "").strip()
            section_blocks.append(
                f"[section:{ch_slug}]: #\n\n{ch_summary}\n\n[/section:{ch_slug}]: #"
            )

        root_content = "\n\n".join(root_lines) + "\n\n" + "\n\n".join(section_blocks)
        (book_path / "_node.md").write_text(root_content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate a Nook world (dat/ or world folder or .db) to a Lens project",
    )
    parser.add_argument(
        "nook_input",
        type=Path,
        help="Nook dat/ directory, or dat/worlds/<slug>/ folder, or path to <slug>.db",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Path to create or update Lens project",
    )
    parser.add_argument(
        "--world",
        type=str,
        default=None,
        metavar="SLUG",
        help="World slug (required when nook_input is the Nook dat/ directory)",
    )
    args = parser.parse_args()

    try:
        nook = resolve_nook_paths(args.nook_input, args.world)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    db_path = nook.db_path
    if not db_path.is_file():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        return 1

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    media_root = nook.media_root
    if media_root is None:
        print(
            "Note: No usable media_path in world config (or path missing); scene media embeds skipped.",
            file=sys.stderr,
        )

    try:
        lens_toml = output / "lens.toml"
        if not lens_toml.exists():
            lens_toml.write_text(
                "[project]\n# narrative selection set by 'lens use <slug>'\n",
                encoding="utf-8",
            )

        migrate_knowledge(conn, output)
        migrate_narrative(conn, output, media_root=media_root)
        if media_root is not None:
            _set_lens_mount_point(lens_toml, media_root)

        print(f"Migrated Nook world to Lens project at {output}")
        print(f"  - database: {db_path}")
        print("  - knowledge/: migrated")
        print("  - narrative/: one tree per book")
        if media_root:
            print(f"  - mount_point: {media_root} (Nook media_path; embeds are relative to it)")
        print("  - Run 'lens use <book-slug>' to select a narrative")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
