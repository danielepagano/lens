"""Unit tests for lens.storage: git-backed transactional storage."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.storage import Storage, detect_pending_owner_from_diff, make_owner_id


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return r.stdout


def _init_repo(tmp: Path) -> Path:
    """Create a git repo with an initial commit so diffs work."""
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, capture_output=True, check=True,
    )
    return tmp


class TestMakeOwnerId(unittest.TestCase):
    def test_with_ann_id(self) -> None:
        self.assertEqual(
            make_owner_id("section", "ch1", "narrative/test/_node.md"),
            "section:ch1@narrative/test/_node.md",
        )

    def test_without_ann_id_with_line(self) -> None:
        self.assertEqual(
            make_owner_id("write", None, "narrative/test/_node.md", 15),
            "write@narrative/test/_node.md:15",
        )

    def test_without_ann_id_or_line(self) -> None:
        self.assertEqual(
            make_owner_id("write", None, "narrative/test/_node.md"),
            "write@narrative/test/_node.md",
        )


class TestHasPending(unittest.TestCase):
    def test_no_pending_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            s = Storage(root)
            self.assertFalse(s.has_pending())

    def test_detects_tracked_modification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / ".gitkeep").write_text("changed")
            s = Storage(root)
            self.assertTrue(s.has_pending())

    def test_detects_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / "newfile.md").write_text("hello")
            s = Storage(root)
            self.assertTrue(s.has_pending())


class TestStageAll(unittest.TestCase):
    def test_stages_modifications_and_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / ".gitkeep").write_text("mod")
            (root / "new.md").write_text("new")
            s = Storage(root)
            self.assertTrue(s.has_pending())
            s.stage_all()
            self.assertFalse(s.has_pending())
            # Files are staged (git diff --cached shows them)
            cached = _git(root, "diff", "--cached", "--name-only")
            self.assertIn(".gitkeep", cached)
            self.assertIn("new.md", cached)


class TestAbort(unittest.TestCase):
    def test_discards_modifications(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / ".gitkeep").write_text("dirty")
            s = Storage(root)
            self.assertTrue(s.has_pending())
            s.abort()
            self.assertFalse(s.has_pending())
            self.assertEqual((root / ".gitkeep").read_text(), "")

    def test_removes_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / "untracked.md").write_text("hi")
            s = Storage(root)
            self.assertTrue(s.has_pending())
            s.abort()
            self.assertFalse(s.has_pending())
            self.assertFalse((root / "untracked.md").exists())


class TestCheckpoint(unittest.TestCase):
    def test_creates_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / "file.md").write_text("content")
            s = Storage(root)
            s.checkpoint("add file")
            self.assertFalse(s.has_pending())
            log = _git(root, "log", "--oneline")
            self.assertIn("add file", log)


class TestFileOperations(unittest.TestCase):
    def test_write_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            s = Storage(root)
            target = root / "subdir" / "test.md"
            s.write_file(target, "hello")
            self.assertEqual(target.read_text(), "hello")
            self.assertTrue(s.has_pending())

    def test_write_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            s = Storage(root)
            target = root / "bin.dat"
            s.write_file_bytes(target, b"\x00\x01")
            self.assertEqual(target.read_bytes(), b"\x00\x01")

    def test_delete_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            target = root / "to_delete.md"
            target.write_text("x")
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "add")
            s = Storage(root)
            s.delete_file(target)
            self.assertFalse(target.exists())
            self.assertTrue(s.has_pending())

    def test_delete_missing_file_no_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            s = Storage(root)
            s.delete_file(root / "nope.md")

    def test_mkdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            s = Storage(root)
            d = root / "a" / "b"
            s.mkdir(d)
            self.assertTrue(d.is_dir())

    def test_rmdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            d = root / "empty"
            d.mkdir()
            s = Storage(root)
            s.rmdir(d)
            self.assertFalse(d.exists())

    def test_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            src = root / "old.md"
            src.write_text("data")
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "add")
            s = Storage(root)
            dst = root / "new.md"
            s.rename(src, dst)
            self.assertFalse(src.exists())
            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_text(), "data")


class TestPendingFiles(unittest.TestCase):
    def test_lists_modified_and_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / ".gitkeep").write_text("mod")
            (root / "new.md").write_text("new")
            s = Storage(root)
            files = s.pending_files()
            self.assertIn(".gitkeep", files)
            self.assertIn("new.md", files)


class TestOwnershipAutoStage(unittest.TestCase):
    def test_system_owner_stages_pending(self) -> None:
        """A system command (owner=None) always stages pending changes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / "file.md").write_text("[section:ch1]: #\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "track")
            (root / "file.md").write_text("[section:ch1]: #\nmodified\n")
            self.assertTrue(Storage(root).has_pending())

            s = Storage(root)
            s.write_file(root / "other.md", "system write")
            # The previous pending changes should have been staged
            cached = _git(root, "diff", "--cached", "--name-only")
            self.assertIn("file.md", cached)

    def test_same_operator_continues(self) -> None:
        """Same operator+id continues without staging."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            node = root / "narrative" / "test" / "_node.md"
            node.parent.mkdir(parents=True)
            node.write_text("# test\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "track")

            node.write_text("# test\n\n[section:ch1]: #\n")

            owner = make_owner_id("section", "ch1", "narrative/test/_node.md")
            s = Storage(root, owner=owner)
            s.write_file(root / "narrative" / "test" / "ch1" / "_node.md", "# ch1\n")
            # The original pending change should NOT have been staged
            cached = _git(root, "diff", "--cached", "--name-only")
            self.assertEqual(cached.strip(), "")

    def test_different_operator_stages(self) -> None:
        """A different operator stages the previous owner's changes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            node = root / "narrative" / "test" / "_node.md"
            node.parent.mkdir(parents=True)
            node.write_text("# test\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "track")

            node.write_text("# test\n\n[section:ch1]: #\n")

            owner = make_owner_id("write", None, "narrative/test/ch1/_node.md", 1)
            s = Storage(root, owner=owner)
            ch1 = root / "narrative" / "test" / "ch1" / "_node.md"
            ch1.parent.mkdir(parents=True)
            s.write_file(ch1, "# ch1\n")
            # Previous owner's pending should have been staged
            cached = _git(root, "diff", "--cached", "--name-only")
            self.assertIn("narrative/test/_node.md", cached)


class TestDetectPendingOwnerFromDiff(unittest.TestCase):
    def test_added_single_line_annotation(self) -> None:
        diff = (
            "diff --git a/narrative/test/_node.md b/narrative/test/_node.md\n"
            "--- a/narrative/test/_node.md\n"
            "+++ b/narrative/test/_node.md\n"
            "@@ -1,2 +1,4 @@\n"
            " # test\n"
            " \n"
            "+[section:ch1]: #\n"
            "+\n"
        )
        owner = detect_pending_owner_from_diff(diff)
        self.assertEqual(owner, "section:ch1@narrative/test/_node.md")

    def test_added_multiline_annotation(self) -> None:
        diff = (
            "diff --git a/n/_node.md b/n/_node.md\n"
            "--- a/n/_node.md\n"
            "+++ b/n/_node.md\n"
            "@@ -1 +1,4 @@\n"
            " # root\n"
            "+[write\n"
            "+  prompt: hello\n"
            "+]: #\n"
        )
        owner = detect_pending_owner_from_diff(diff)
        self.assertEqual(owner, "write@n/_node.md:2")

    def test_removed_annotation_mode3(self) -> None:
        diff = (
            "diff --git a/n/_node.md b/n/_node.md\n"
            "--- a/n/_node.md\n"
            "+++ b/n/_node.md\n"
            "@@ -1,4 +1,2 @@\n"
            " # root\n"
            "-[edit:fix1]: #\n"
            "-old text\n"
            "+new text\n"
        )
        owner = detect_pending_owner_from_diff(diff)
        self.assertEqual(owner, "edit:fix1@n/_node.md")

    def test_added_preferred_over_removed(self) -> None:
        diff = (
            "diff --git a/n/_node.md b/n/_node.md\n"
            "--- a/n/_node.md\n"
            "+++ b/n/_node.md\n"
            "@@ -1,4 +1,4 @@\n"
            " # root\n"
            "-[write\n"
            "-  steps: 1\n"
            "+[write\n"
            "+  steps: 2\n"
            " ]: #\n"
        )
        owner = detect_pending_owner_from_diff(diff)
        # Added line should be preferred
        self.assertIsNotNone(owner)
        assert owner is not None
        self.assertTrue(owner.startswith("write@"))

    def test_no_annotations_returns_none(self) -> None:
        diff = (
            "diff --git a/knowledge/place/nyc.md b/knowledge/place/nyc.md\n"
            "--- a/knowledge/place/nyc.md\n"
            "+++ b/knowledge/place/nyc.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.assertIsNone(detect_pending_owner_from_diff(diff))

    def test_empty_diff_returns_none(self) -> None:
        self.assertIsNone(detect_pending_owner_from_diff(""))

    def test_close_tag_not_detected_as_owner(self) -> None:
        diff = (
            "diff --git a/n/_node.md b/n/_node.md\n"
            "--- a/n/_node.md\n"
            "+++ b/n/_node.md\n"
            "@@ -3,0 +4,1 @@\n"
            "+[/section:ch1]: #\n"
        )
        self.assertIsNone(detect_pending_owner_from_diff(diff))
