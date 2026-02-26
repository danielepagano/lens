#!/usr/bin/env python3
"""
Migrate a Nook SQLite database to a Lens project.

Reads a Nook world DB, creates a Lens project in the output folder (no git init).
Preserves all knowledge and books text. Creates sections for chapters and scenes
with Nook summaries as section content. Ignores media.

Usage:
    python scripts/nook_to_lens.py <nook_db_path> <lens_output_folder>
"""

from __future__ import annotations

import argparse
import io
import re
import sqlite3
import sys
from pathlib import Path

# Add project root so we can import tomli_w
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tomli_w

_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_VALUE_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


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


def migrate_narrative(conn: sqlite3.Connection, root: Path) -> None:
    """Migrate books/chapters/scenes to Lens narrative with sections."""
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pin'"
    )
    has_pins = bool(cursor.fetchone())

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
        description="Migrate Nook DB to Lens project",
    )
    parser.add_argument(
        "nook_db",
        type=Path,
        help="Path to Nook world SQLite database",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Path to create Lens project",
    )
    args = parser.parse_args()

    db_path = args.nook_db.resolve()
    if not db_path.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        return 1

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        lens_toml = output / "lens.toml"
        if not lens_toml.exists():
            lens_toml.write_text("[project]\n# narrative selection set by 'lens use <slug>'\n", encoding="utf-8")

        migrate_knowledge(conn, output)
        migrate_narrative(conn, output)

        print(f"Migrated Nook DB to Lens project at {output}")
        print("  - knowledge/: migrated")
        print("  - narrative/: one narrative per book")
        print("  - Run 'lens use <book-slug>' to select a narrative")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
