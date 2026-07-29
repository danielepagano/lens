"""Tests for the attach command (core layer) and get_mount_point config helper."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.attach import (
    SUPPORTED_EXTENSIONS,
    attach,
    attach_layered,
    build_embed,
    build_layered_embed,
    find_files_with_mount_refs,
    get_mount_ref_line_numbers,
    insert_embed_at_line,
    media_type,
    remove_media_references,
    update_media_references,
    validate_attach_insertion_point,
)
from lens.core.exceptions import LensException
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession, get_mount_point
from lens.core.storage import Storage


# ---------------------------------------------------------------------------
# Helpers shared with other core tests
# ---------------------------------------------------------------------------


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, check=True)
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)
    return tmp


def _make_project(tmp: Path, mount_subdir: str | None = None) -> tuple[Path, NarrativeNode]:
    """Create a minimal Lens project. Optionally configure mount_point."""
    mount_line = '\nmount_point = "media"' if mount_subdir else ""
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "story"{mount_line}\n')
    narrative_dir = tmp / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# Story\n\nSome content.\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    if mount_subdir:
        mount_dir = tmp / mount_subdir
        mount_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True)
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


# ---------------------------------------------------------------------------
# get_mount_point tests
# ---------------------------------------------------------------------------


class TestGetMountPoint(unittest.TestCase):

    def test_no_lens_toml_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(get_mount_point(Path(tmp)))

    def test_no_mount_point_field_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lens.toml").write_text('[project]\nnarrative = "story"\n')
            self.assertIsNone(get_mount_point(Path(tmp)))

    def test_relative_mount_point_resolves_to_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "media"\n')
            result = get_mount_point(p)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result, (p / "media").resolve())

    def test_absolute_mount_point_returned_as_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            abs_path = str(p / "mnt")
            (p / "lens.toml").write_text(f'[project]\nmount_point = "{abs_path}"\n')
            result = get_mount_point(p)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result, Path(abs_path))

    def test_empty_string_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lens.toml").write_text('[project]\nmount_point = ""\n')
            self.assertIsNone(get_mount_point(Path(tmp)))


# ---------------------------------------------------------------------------
# media_type and build_embed unit tests
# ---------------------------------------------------------------------------


class TestMediaType(unittest.TestCase):

    def test_image_extensions(self) -> None:
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            self.assertEqual(media_type(ext), "image", f"expected image for {ext}")

    def test_video_extensions(self) -> None:
        for ext in (".mp4", ".webm", ".mov", ".avi"):
            self.assertEqual(media_type(ext), "video", f"expected video for {ext}")

    def test_document_extensions(self) -> None:
        for ext in (".pdf", ".txt", ".md"):
            self.assertEqual(media_type(ext), "document", f"expected document for {ext}")


class TestBuildEmbed(unittest.TestCase):

    def test_image_produces_markdown_image(self) -> None:
        embed = build_embed("images/hero.jpg", ".jpg")
        self.assertEqual(embed, "![hero.jpg](/mount/file/images/hero.jpg)")

    def test_video_produces_video_tag(self) -> None:
        embed = build_embed("clips/intro.mp4", ".mp4")
        self.assertIn("<video", embed)
        self.assertIn("/mount/file/clips/intro.mp4", embed)
        self.assertIn("controls", embed)

    def test_document_produces_link(self) -> None:
        embed = build_embed("docs/map.pdf", ".pdf")
        self.assertEqual(embed, "[map.pdf](/mount/file/docs/map.pdf)")

    def test_text_file_uses_preview_url(self) -> None:
        embed = build_embed("notes/readme.txt", ".txt")
        self.assertEqual(embed, "[readme.txt](/mount/preview/notes/readme.txt)")

    def test_markdown_file_uses_preview_url(self) -> None:
        embed = build_embed("notes/chapter.md", ".md")
        self.assertEqual(embed, "[chapter.md](/mount/preview/notes/chapter.md)")

    def test_leading_slash_stripped_from_url(self) -> None:
        embed = build_embed("/subdir/photo.png", ".png")
        self.assertIn("/mount/file/subdir/photo.png", embed)
        self.assertNotIn("//", embed.split("(")[-1])

    def test_supported_extensions_covers_all_media_types(self) -> None:
        """Every supported extension maps to a known media type."""
        for ext in SUPPORTED_EXTENSIONS:
            t = media_type(ext)
            self.assertIn(t, ("image", "video", "document"))


class TestBuildLayeredEmbed(unittest.TestCase):

    def test_contains_both_urls_and_composite_class(self) -> None:
        embed = build_layered_embed("bg/scene.jpg", "fg/amy.png")
        self.assertIn('class="lens-vn-composite"', embed)
        self.assertIn("/mount/file/bg/scene.jpg", embed)
        self.assertIn("/mount/file/fg/amy.png", embed)
        self.assertIn('class="lens-vn-bg"', embed)
        self.assertIn('class="lens-vn-fg"', embed)

    def test_is_single_line(self) -> None:
        embed = build_layered_embed("bg/scene.jpg", "fg/amy.png")
        self.assertNotIn("\n", embed)

    def test_leading_slash_stripped_from_urls(self) -> None:
        embed = build_layered_embed("/bg/scene.jpg", "/fg/amy.png")
        self.assertIn("/mount/file/bg/scene.jpg", embed)
        self.assertIn("/mount/file/fg/amy.png", embed)
        self.assertNotIn("file//bg", embed)

    def test_escapes_filename_with_quotes(self) -> None:
        embed = build_layered_embed('bg/we"ird.jpg', "fg/amy.png")
        self.assertNotIn('"we"ird.jpg"', embed)
        self.assertIn("&quot;", embed)


# ---------------------------------------------------------------------------
# attach() — preview mode
# ---------------------------------------------------------------------------


class TestAttachPreview(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.node = _make_project(tmp, mount_subdir="media")
        # Place a test image in the mount directory
        (tmp / "media" / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0")  # JPEG magic bytes

    def test_preview_returns_type_and_ext(self) -> None:
        session = ProjectSession(self.root, self.root)
        result = attach(session, "hero.jpg", preview=True)
        self.assertEqual(result["type"], "image")
        self.assertEqual(result["ext"], ".jpg")
        self.assertEqual(result["path"], "hero.jpg")

    def test_unsupported_extension_raises(self) -> None:
        session = ProjectSession(self.root, self.root)
        with self.assertRaises(LensException) as ctx:
            attach(session, "file.sh", preview=True)
        self.assertIn("unsupported extension", str(ctx.exception))

    def test_missing_file_raises(self) -> None:
        session = ProjectSession(self.root, self.root)
        with self.assertRaises(LensException) as ctx:
            attach(session, "nonexistent.png", preview=True)
        self.assertIn("file not found", str(ctx.exception))

    def test_path_traversal_raises(self) -> None:
        session = ProjectSession(self.root, self.root)
        with self.assertRaises(LensException) as ctx:
            attach(session, "../../etc/passwd.jpg", preview=True)
        self.assertIn("escapes", str(ctx.exception))

    def test_no_mount_point_raises(self) -> None:
        # Create a project without mount_point
        with tempfile.TemporaryDirectory() as tmp2:
            p = Path(tmp2)
            _init_repo(p)
            _, _ = _make_project(p)  # no mount_subdir
            session = ProjectSession(p, p)
            with self.assertRaises(LensException) as ctx:
                attach(session, "hero.jpg", preview=True)
            self.assertIn("no mount_point", str(ctx.exception))


# ---------------------------------------------------------------------------
# attach() — insert mode (writes embed at cursor)
# ---------------------------------------------------------------------------


class TestAttachInsert(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.node = _make_project(tmp, mount_subdir="media")
        mount = tmp / "media"
        (mount / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        (mount / "clip.mp4").write_bytes(b"\x00\x00\x00\x18")
        (mount / "doc.pdf").write_bytes(b"%PDF-1.4")

    def test_image_embed_appended_to_cursor_node(self) -> None:
        session = ProjectSession(self.root, self.root)
        before = self.node.md_path().read_text()
        result = attach(session, "hero.jpg")
        after = self.node.md_path().read_text()
        self.assertEqual(result["type"], "image")
        embed = result["embed"]
        self.assertIn(embed, after)
        self.assertTrue(after.startswith(before.rstrip("\n")))

    def test_video_embed_contains_video_tag(self) -> None:
        session = ProjectSession(self.root, self.root)
        result = attach(session, "clip.mp4")
        after = self.node.md_path().read_text()
        self.assertEqual(result["type"], "video")
        self.assertIn("<video", after)
        self.assertIn("/mount/file/clip.mp4", after)

    def test_document_embed_is_link(self) -> None:
        session = ProjectSession(self.root, self.root)
        result = attach(session, "doc.pdf")
        after = self.node.md_path().read_text()
        self.assertEqual(result["type"], "document")
        self.assertIn("[doc.pdf]", after)
        self.assertIn("/mount/file/doc.pdf", after)

    def test_insert_leaves_pending_change_in_storage(self) -> None:
        session = ProjectSession(self.root, self.root)
        attach(session, "hero.jpg")
        storage = Storage(self.root, owner=None)
        self.assertTrue(storage.has_pending())

    def test_result_contains_embed_key(self) -> None:
        session = ProjectSession(self.root, self.root)
        result = attach(session, "hero.jpg")
        self.assertIn("embed", result)
        self.assertIn("/mount/file/hero.jpg", result["embed"])

    def test_insert_at_line_pushes_existing_content_down(self) -> None:
        session = ProjectSession(self.root, self.root)
        attach(session, "hero.jpg", address="/", line=3)
        after = self.node.md_path().read_text()
        self.assertIn("\n\n![", after)
        self.assertIn("Some content.", after)
        self.assertLess(after.index("!["), after.index("Some content."))

    def test_insert_at_line_with_existing_blank_no_triple_newline(self) -> None:
        session = ProjectSession(self.root, self.root)
        path = self.node.md_path()
        path.write_text("# Story\n\nSome content.\n\n")
        attach(session, "hero.jpg", address="/", line=3)
        after = path.read_text()
        self.assertNotIn("\n\n\n![", after)
        self.assertIn("\n\n![", after)

    def test_rejects_line_inside_multiline_annotation_tag(self) -> None:
        session = ProjectSession(self.root, self.root)
        path = self.node.md_path()
        path.write_text(
            "# T\n\n[write\n  prompt: x\n]: #\n\nBody.\n"
        )
        with self.assertRaises(LensException) as ctx:
            attach(session, "hero.jpg", address="/", line=4)
        self.assertIn("annotation tag", str(ctx.exception))

    def test_allows_line_after_closing_tag_line(self) -> None:
        session = ProjectSession(self.root, self.root)
        path = self.node.md_path()
        path.write_text(
            "# T\n\n[write\n  prompt: x\n]: #\n\nBody.\n"
        )
        attach(session, "hero.jpg", address="/", line=6)
        after = path.read_text()
        self.assertIn("/mount/file/hero.jpg", after)


class TestAttachLayered(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        tmp = Path(self._tmp)
        _init_repo(tmp)
        self.root, self.node = _make_project(tmp, mount_subdir="media")
        mount = tmp / "media"
        (mount / "bg.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        (mount / "fg.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (mount / "clip.mp4").write_bytes(b"\x00\x00\x00\x18")

    def test_inserts_composite_embed_at_cursor_node(self) -> None:
        session = ProjectSession(self.root, self.root)
        before = self.node.md_path().read_text()
        result = attach_layered(session, "bg.jpg", "fg.png")
        after = self.node.md_path().read_text()
        self.assertEqual(result["type"], "image")
        self.assertEqual(result["bg_path"], "bg.jpg")
        self.assertEqual(result["fg_path"], "fg.png")
        self.assertIn(result["embed"], after)
        self.assertTrue(after.startswith(before.rstrip("\n")))
        self.assertIn("/mount/file/bg.jpg", after)
        self.assertIn("/mount/file/fg.png", after)

    def test_leaves_pending_change_in_storage(self) -> None:
        session = ProjectSession(self.root, self.root)
        attach_layered(session, "bg.jpg", "fg.png")
        storage = Storage(self.root, owner=None)
        self.assertTrue(storage.has_pending())

    def test_non_image_bg_raises(self) -> None:
        session = ProjectSession(self.root, self.root)
        with self.assertRaises(LensException) as ctx:
            attach_layered(session, "clip.mp4", "fg.png")
        self.assertIn("requires images", str(ctx.exception))

    def test_non_image_fg_raises(self) -> None:
        session = ProjectSession(self.root, self.root)
        with self.assertRaises(LensException) as ctx:
            attach_layered(session, "bg.jpg", "clip.mp4")
        self.assertIn("requires images", str(ctx.exception))

    def test_missing_bg_file_raises(self) -> None:
        session = ProjectSession(self.root, self.root)
        with self.assertRaises(LensException) as ctx:
            attach_layered(session, "nope.jpg", "fg.png")
        self.assertIn("file not found", str(ctx.exception))

    def test_missing_fg_file_raises(self) -> None:
        session = ProjectSession(self.root, self.root)
        with self.assertRaises(LensException) as ctx:
            attach_layered(session, "bg.jpg", "nope.png")
        self.assertIn("file not found", str(ctx.exception))

    def test_no_mount_point_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp2:
            p = Path(tmp2)
            _init_repo(p)
            _make_project(p)  # no mount_subdir
            session = ProjectSession(p, p)
            with self.assertRaises(LensException) as ctx:
                attach_layered(session, "bg.jpg", "fg.png")
            self.assertIn("no mount_point", str(ctx.exception))

    def test_insert_at_line_pushes_existing_content_down(self) -> None:
        session = ProjectSession(self.root, self.root)
        attach_layered(session, "bg.jpg", "fg.png", address="/", line=3)
        after = self.node.md_path().read_text()
        self.assertIn("Some content.", after)
        self.assertLess(after.index("lens-vn-composite"), after.index("Some content."))


class TestAttachValidateAndInsert(unittest.TestCase):

    def test_validate_rejects_front_matter_line(self) -> None:
        text = (
            "[\n"
            "    kb_pin:\n"
            "        - thing\n"
            "]: #\n"
            "\n"
            "Story content here.\n"
        )
        with self.assertRaises(LensException):
            validate_attach_insertion_point(text, 2)

    def test_validate_rejects_line_one_when_front_matter_present(self) -> None:
        text = (
            "[\n"
            "    kb_pin:\n"
            "        - thing\n"
            "]: #\n"
            "\n"
            "Story content here.\n"
        )
        with self.assertRaises(LensException):
            validate_attach_insertion_point(text, 1)

    def test_validate_allows_line_right_after_front_matter(self) -> None:
        text = (
            "[\n"
            "    kb_pin:\n"
            "        - thing\n"
            "]: #\n"
            "\n"
            "Story content here.\n"
        )
        validate_attach_insertion_point(text, 5)

    def test_insert_embed_at_line(self) -> None:
        embed = "![x](/mount/file/x.jpg)"
        out = insert_embed_at_line("a\nb\n", 2, embed)
        self.assertIn("a\n\n" + embed + "\n\nb", out)

    def test_insert_at_line_one_prepends_above_first_line(self) -> None:
        embed = "![x](/mount/file/x.jpg)"
        out = insert_embed_at_line("a\nb\n", 1, embed)
        self.assertTrue(out.startswith(embed + "\n\na"))

    def test_insert_at_len_plus_one_appends_to_end(self) -> None:
        content = "a\nb\nc"
        embed = "![x](/mount/file/x.jpg)"
        lines = content.split("\n")
        out = insert_embed_at_line(content, len(lines) + 1, embed)
        self.assertTrue(out.startswith("a\nb\nc"))
        self.assertIn(embed, out)
        self.assertGreater(out.index(embed), out.index("c"))

    def test_insert_at_mid_file_pushes_subsequent_lines_down(self) -> None:
        content = "line one.\nline two.\nline three.\n"
        embed = "![x](/mount/file/x.jpg)"
        out = insert_embed_at_line(content, 2, embed)
        self.assertLess(out.index("line one."), out.index(embed))
        self.assertLess(out.index(embed), out.index("line two."))
        self.assertLess(out.index("line two."), out.index("line three."))

    def test_validate_rejects_line_zero(self) -> None:
        with self.assertRaises(LensException):
            validate_attach_insertion_point("a\nb\n", 0)

    def test_validate_rejects_line_past_end_plus_one(self) -> None:
        text = "a\nb\nc"
        lines = text.split("\n")
        with self.assertRaises(LensException):
            validate_attach_insertion_point(text, len(lines) + 2)

    def test_validate_allows_line_at_end_plus_one(self) -> None:
        text = "a\nb\nc"
        lines = text.split("\n")
        validate_attach_insertion_point(text, len(lines) + 1)

    def test_validate_allows_first_line_of_annotation(self) -> None:
        text = "Body.\n[write\n  prompt: x\n]: #\nMore.\n"
        validate_attach_insertion_point(text, 2)


# ---------------------------------------------------------------------------
# find_files_with_mount_refs / update_media_references
# ---------------------------------------------------------------------------


class TestFindFilesWithMountRefs(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        _init_repo(self.root)
        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "story"\nmount_point = "media"\n'
        )
        self.narrative = self.root / "narrative" / "story"
        self.narrative.mkdir(parents=True)
        (self.root / "knowledge").mkdir()

    def _write_narrative(self, name: str, content: str) -> Path:
        p = self.narrative / name
        p.write_text(content, encoding="utf-8")
        return p

    def _write_knowledge(self, type_name: str, key: str, content: str) -> Path:
        d = self.root / "knowledge" / type_name
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{key}.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_detects_image_embed(self) -> None:
        self._write_narrative(
            "ch1.md", "# Ch1\n\n![hero.jpg](/mount/file/images/hero.jpg)\n\nText.\n"
        )
        hits = find_files_with_mount_refs(self.root, "images/hero.jpg")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].name, "ch1.md")

    def test_detects_video_embed(self) -> None:
        self._write_narrative(
            "ch1.md",
            "# Ch1\n\n"
            '<video src="/mount/file/clips/intro.mp4" controls></video>\n\n'
            "Text.\n",
        )
        hits = find_files_with_mount_refs(self.root, "clips/intro.mp4")
        self.assertEqual(len(hits), 1)

    def test_detects_link_embed(self) -> None:
        self._write_narrative(
            "ch1.md", "# Ch1\n\n[readme.txt](/mount/preview/notes/readme.txt)\n\nText.\n"
        )
        hits = find_files_with_mount_refs(self.root, "notes/readme.txt")
        self.assertEqual(len(hits), 1)

    def test_handles_url_encoded_path(self) -> None:
        self._write_narrative(
            "ch1.md",
            "# Ch1\n\n![my%20file.jpg](/mount/file/images/my%20file.jpg)\n\nText.\n",
        )
        hits = find_files_with_mount_refs(self.root, "images/my file.jpg")
        self.assertEqual(len(hits), 1)

    def test_returns_empty_when_no_match(self) -> None:
        self._write_narrative("ch1.md", "# Ch1\n\nJust text.\n")
        hits = find_files_with_mount_refs(self.root, "images/hero.jpg")
        self.assertEqual(len(hits), 0)

    def test_scans_knowledge_dir(self) -> None:
        self._write_knowledge(
            "person",
            "amy",
            "# Amy\n\n![portrait](/mount/file/portraits/amy.jpg)\n",
        )
        hits = find_files_with_mount_refs(self.root, "portraits/amy.jpg")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].name, "amy.md")

    def test_finds_multiple_files(self) -> None:
        self._write_narrative(
            "ch1.md", "# Ch1\n\n![hero.jpg](/mount/file/images/hero.jpg)\n"
        )
        self._write_narrative(
            "ch2.md", "# Ch2\n\n![hero.jpg](/mount/file/images/hero.jpg)\n"
        )
        hits = find_files_with_mount_refs(self.root, "images/hero.jpg")
        self.assertEqual(len(hits), 2)

    def test_skips_nonexistent_dirs(self) -> None:
        import shutil as _shutil

        _shutil.rmtree(self.narrative)
        hits = find_files_with_mount_refs(self.root, "images/hero.jpg")
        self.assertEqual(len(hits), 0)


class TestUpdateMediaReferences(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        _init_repo(self.root)
        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "story"\nmount_point = "media"\n'
        )
        self.narrative = self.root / "narrative" / "story"
        self.narrative.mkdir(parents=True)
        (self.root / "knowledge").mkdir()

    def _write_narrative(self, name: str, content: str) -> Path:
        p = self.narrative / name
        p.write_text(content, encoding="utf-8")
        return p

    def _write_knowledge(self, type_name: str, key: str, content: str) -> Path:
        d = self.root / "knowledge" / type_name
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{key}.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_replaces_in_narrative(self) -> None:
        p = self._write_narrative(
            "ch1.md", "# Ch1\n\n![hero.jpg](/mount/file/images/hero.jpg)\n"
        )
        count = update_media_references(
            self.root, "images/hero.jpg", "portraits/hero.jpg"
        )
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertIn("/mount/file/portraits/hero.jpg", text)
        self.assertNotIn("/mount/file/images/hero.jpg", text)

    def test_replaces_in_knowledge(self) -> None:
        p = self._write_knowledge(
            "person",
            "amy",
            "# Amy\n\n![amy](/mount/file/portraits/amy.jpg)\n",
        )
        count = update_media_references(
            self.root, "portraits/amy.jpg", "avatars/amy.jpg"
        )
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertIn("/mount/file/avatars/amy.jpg", text)
        self.assertNotIn("/mount/file/portraits/amy.jpg", text)

    def test_replaces_video_embed(self) -> None:
        p = self._write_narrative(
            "ch1.md",
            "# Ch1\n\n"
            '<video src="/mount/file/clips/old.mp4" controls></video>\n',
        )
        count = update_media_references(
            self.root, "clips/old.mp4", "clips/new.mp4"
        )
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertIn("/mount/file/clips/new.mp4", text)
        self.assertNotIn("/mount/file/clips/old.mp4", text)

    def test_replaces_preview_embed(self) -> None:
        p = self._write_narrative(
            "ch1.md",
            "# Ch1\n\n[readme.txt](/mount/preview/notes/readme.txt)\n",
        )
        count = update_media_references(
            self.root, "notes/readme.txt", "docs/readme.txt"
        )
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertIn("/mount/preview/docs/readme.txt", text)
        self.assertNotIn("/mount/preview/notes/readme.txt", text)

    def test_replaces_url_encoded_path(self) -> None:
        p = self._write_narrative(
            "ch1.md",
            "# Ch1\n\n![my%20file.jpg](/mount/file/images/my%20file.jpg)\n",
        )
        count = update_media_references(
            self.root, "images/my file.jpg", "images/renamed.jpg"
        )
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertIn("/mount/file/images/renamed.jpg", text)

    def test_returns_correct_count(self) -> None:
        self._write_narrative(
            "ch1.md", "# Ch1\n\n![h](/mount/file/images/h.jpg)\n"
        )
        self._write_narrative(
            "ch2.md", "# Ch2\n\n![h](/mount/file/images/h.jpg)\n"
        )
        self._write_narrative(
            "ch3.md", "# Ch3\n\nNo media here.\n"
        )
        count = update_media_references(
            self.root, "images/h.jpg", "images/new-h.jpg"
        )
        self.assertEqual(count, 2)

    def test_noop_when_no_refs(self) -> None:
        p = self._write_narrative("ch1.md", "# Ch1\n\nJust text.\n")
        original = p.read_text()
        count = update_media_references(
            self.root, "images/hero.jpg", "images/new.jpg"
        )
        self.assertEqual(count, 0)
        self.assertEqual(p.read_text(), original)

    def test_preserves_surrounding_content(self) -> None:
        content = "# Ch1\n\nSome intro.\n\n![hero.jpg](/mount/file/images/hero.jpg)\n\nMore text.\n"
        p = self._write_narrative("ch1.md", content)
        update_media_references(
            self.root, "images/hero.jpg", "portraits/hero.jpg"
        )
        text = p.read_text()
        self.assertIn("# Ch1", text)
        self.assertIn("Some intro.", text)
        self.assertIn("More text.", text)
        self.assertIn("![hero.jpg](/mount/file/portraits/hero.jpg)", text)

    def test_multiple_embed_types_in_same_file(self) -> None:
        content = (
            "# Ch1\n\n"
            "![img](/mount/file/old.jpg)\n\n"
            '<video src="/mount/file/old.mp4" controls></video>\n\n'
            "[doc](/mount/preview/old.md)\n"
        )
        p = self._write_narrative("ch1.md", content)
        count = update_media_references(self.root, "old.jpg", "new.jpg")
        # Only the image should be updated (old.mp4 and old.md are different paths)
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertIn("/mount/file/new.jpg", text)
        self.assertIn("/mount/file/old.mp4", text)
        self.assertIn("/mount/preview/old.md", text)


# ---------------------------------------------------------------------------
# get_mount_ref_line_numbers / remove_media_references
# ---------------------------------------------------------------------------


class TestGetMountRefLineNumbers(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        _init_repo(self.root)
        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "story"\nmount_point = "media"\n'
        )
        self.narrative = self.root / "narrative" / "story"
        self.narrative.mkdir(parents=True)
        (self.root / "knowledge").mkdir()

    def _write_narrative(self, name: str, content: str) -> Path:
        p = self.narrative / name
        p.write_text(content, encoding="utf-8")
        return p

    def _write_knowledge(self, type_name: str, key: str, content: str) -> Path:
        d = self.root / "knowledge" / type_name
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{key}.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_returns_line_numbers_for_single_ref(self) -> None:
        self._write_narrative(
            "ch1.md", "# Ch1\n\n![hero.jpg](/mount/file/images/hero.jpg)\n\nText.\n"
        )
        refs = get_mount_ref_line_numbers(self.root, "images/hero.jpg")
        self.assertIn("narrative/story/ch1.md", refs)
        self.assertEqual(refs["narrative/story/ch1.md"], [3])

    def test_returns_multiple_line_numbers(self) -> None:
        content = (
            "# Ch1\n\n"
            "![hero.jpg](/mount/file/images/hero.jpg)\n\n"
            "Some text.\n\n"
            "![hero.jpg](/mount/file/images/hero.jpg)\n"
        )
        self._write_narrative("ch1.md", content)
        refs = get_mount_ref_line_numbers(self.root, "images/hero.jpg")
        self.assertEqual(refs["narrative/story/ch1.md"], [3, 7])

    def test_returns_empty_when_no_refs(self) -> None:
        self._write_narrative("ch1.md", "# Ch1\n\nJust text.\n")
        refs = get_mount_ref_line_numbers(self.root, "images/hero.jpg")
        self.assertEqual(refs, {})

    def test_includes_knowledge_files(self) -> None:
        self._write_knowledge(
            "person", "amy", "# Amy\n\n![amy](/mount/file/portraits/amy.jpg)\n"
        )
        refs = get_mount_ref_line_numbers(self.root, "portraits/amy.jpg")
        self.assertIn("knowledge/person/amy.md", refs)
        self.assertEqual(refs["knowledge/person/amy.md"], [3])

    def test_handles_url_encoded_paths(self) -> None:
        self._write_narrative(
            "ch1.md",
            "# Ch1\n\n![my%20file.jpg](/mount/file/images/my%20file.jpg)\n",
        )
        refs = get_mount_ref_line_numbers(self.root, "images/my file.jpg")
        self.assertIn("narrative/story/ch1.md", refs)


class TestRemoveMediaReferences(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        _init_repo(self.root)
        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "story"\nmount_point = "media"\n'
        )
        self.narrative = self.root / "narrative" / "story"
        self.narrative.mkdir(parents=True)
        (self.root / "knowledge").mkdir()

    def _write_narrative(self, name: str, content: str) -> Path:
        p = self.narrative / name
        p.write_text(content, encoding="utf-8")
        return p

    def _write_knowledge(self, type_name: str, key: str, content: str) -> Path:
        d = self.root / "knowledge" / type_name
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{key}.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_removes_standalone_image_embed(self) -> None:
        content = "# Ch1\n\n![hero.jpg](/mount/file/images/hero.jpg)\n\nText.\n"
        p = self._write_narrative("ch1.md", content)
        count = remove_media_references(self.root, "images/hero.jpg")
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertNotIn("/mount/file/images/hero.jpg", text)
        self.assertIn("# Ch1", text)
        self.assertIn("Text.", text)

    def test_removes_standalone_video_embed(self) -> None:
        content = (
            "# Ch1\n\n"
            '<video src="/mount/file/clips/intro.mp4" controls></video>\n\n'
            "Text.\n"
        )
        p = self._write_narrative("ch1.md", content)
        count = remove_media_references(self.root, "clips/intro.mp4")
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertNotIn("/mount/file/clips/intro.mp4", text)
        self.assertIn("# Ch1", text)
        self.assertIn("Text.", text)

    def test_removes_standalone_link_embed(self) -> None:
        content = "# Ch1\n\n[readme.txt](/mount/preview/notes/readme.txt)\n\nText.\n"
        p = self._write_narrative("ch1.md", content)
        count = remove_media_references(self.root, "notes/readme.txt")
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertNotIn("/mount/preview/notes/readme.txt", text)
        self.assertIn("# Ch1", text)
        self.assertIn("Text.", text)

    def test_cleans_trailing_blank_line(self) -> None:
        content = "# Ch1\n\n![hero.jpg](/mount/file/images/hero.jpg)\n\n\nText.\n"
        p = self._write_narrative("ch1.md", content)
        remove_media_references(self.root, "images/hero.jpg")
        text = p.read_text()
        # Should not have double blank line after removal
        self.assertNotIn("\n\n\n", text)

    def test_noop_when_no_refs(self) -> None:
        content = "# Ch1\n\nJust text.\n"
        p = self._write_narrative("ch1.md", content)
        original = p.read_text()
        count = remove_media_references(self.root, "images/hero.jpg")
        self.assertEqual(count, 0)
        self.assertEqual(p.read_text(), original)

    def test_removes_from_multiple_files(self) -> None:
        self._write_narrative(
            "ch1.md", "# Ch1\n\n![hero.jpg](/mount/file/images/hero.jpg)\n"
        )
        self._write_narrative(
            "ch2.md", "# Ch2\n\n![hero.jpg](/mount/file/images/hero.jpg)\n"
        )
        count = remove_media_references(self.root, "images/hero.jpg")
        self.assertEqual(count, 2)

    def test_removes_from_knowledge(self) -> None:
        self._write_knowledge(
            "person", "amy", "# Amy\n\n![amy](/mount/file/portraits/amy.jpg)\n"
        )
        count = remove_media_references(self.root, "portraits/amy.jpg")
        self.assertEqual(count, 1)

    def test_handles_url_encoded_paths(self) -> None:
        content = "# Ch1\n\n![my%20file.jpg](/mount/file/images/my%20file.jpg)\n\nText.\n"
        p = self._write_narrative("ch1.md", content)
        count = remove_media_references(self.root, "images/my file.jpg")
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertNotIn("/mount/file/images/my%20file.jpg", text)
        self.assertIn("Text.", text)

    def test_multiple_embeds_in_same_file(self) -> None:
        content = (
            "# Ch1\n\n"
            "![hero.jpg](/mount/file/images/hero.jpg)\n\n"
            "Some text.\n\n"
            "![hero.jpg](/mount/file/images/hero.jpg)\n"
        )
        p = self._write_narrative("ch1.md", content)
        count = remove_media_references(self.root, "images/hero.jpg")
        self.assertEqual(count, 1)
        text = p.read_text()
        self.assertNotIn("/mount/file/images/hero.jpg", text)
        self.assertIn("# Ch1", text)
        self.assertIn("Some text.", text)

    def test_preserves_surrounding_content(self) -> None:
        content = "# Ch1\n\nFirst paragraph.\n\n![hero.jpg](/mount/file/images/hero.jpg)\n\nLast paragraph.\n"
        p = self._write_narrative("ch1.md", content)
        remove_media_references(self.root, "images/hero.jpg")
        text = p.read_text()
        self.assertIn("# Ch1", text)
        self.assertIn("First paragraph.", text)
        self.assertIn("Last paragraph.", text)

    def test_handles_empty_file(self) -> None:
        p = self._write_narrative("ch1.md", "")
        count = remove_media_references(self.root, "images/hero.jpg")
        self.assertEqual(count, 0)
        self.assertEqual(p.read_text(), "")
