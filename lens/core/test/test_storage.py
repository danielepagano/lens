"""Unit tests for lens.storage: git-backed transactional storage."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.address import NarrativeAddress
from lens.core.exceptions import LensException
from lens.core.storage import Storage, detect_pending_owner_from_diff


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
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp, capture_output=True, check=True)
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


class TestNarrativeAddressOwner(unittest.TestCase):
    def test_with_ann_id(self) -> None:
        addr = NarrativeAddress.from_file_and_annotation(
            "narrative/test/_node.md",
            operator="section",
            op_id="ch1",
        )
        self.assertEqual(addr.narrative, "test")
        self.assertEqual(addr.key_path, ())
        self.assertEqual(addr.operator, "section")
        self.assertEqual(addr.op_id, "ch1")

    def test_without_ann_id_with_line(self) -> None:
        addr = NarrativeAddress.from_file_and_annotation(
            "narrative/test/_node.md",
            operator="write",
            line=15,
        )
        self.assertEqual(addr.operator, "write")
        self.assertEqual(addr.line, 15)

    def test_without_ann_id_or_line(self) -> None:
        addr = NarrativeAddress.from_file_and_annotation(
            "narrative/test/_node.md",
            operator="write",
        )
        self.assertEqual(addr.operator, "write")
        self.assertIsNone(addr.line)


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


class TestRollback(unittest.TestCase):
    def test_discards_modifications(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / ".gitkeep").write_text("dirty")
            s = Storage(root)
            self.assertTrue(s.has_pending())
            s.rollback()
            self.assertFalse(s.has_pending())
            self.assertEqual((root / ".gitkeep").read_text(), "")

    def test_removes_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / "untracked.md").write_text("hi")
            s = Storage(root)
            self.assertTrue(s.has_pending())
            s.rollback()
            self.assertFalse(s.has_pending())
            self.assertFalse((root / "untracked.md").exists())


class TestWriteFileEmptyReuse(unittest.TestCase):
    def test_empty_write_reuses_existing_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            path = root / "child.md"
            path.write_text("")
            subprocess.run(["git", "add", "child.md"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "empty"],
                cwd=root, capture_output=True, check=True,
            )
            s = Storage(root)
            s.write_file(path, "")
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            self.assertFalse(s.has_pending())

    def test_nonempty_write_replaces_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            path = root / "child.md"
            path.write_text("")
            s = Storage(root)
            s.write_file(path, "hello\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "hello\n")


class TestCheckpoint(unittest.TestCase):
    def test_creates_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            (root / "file.md").write_text("content")
            s = Storage(root)
            s.commit("add file")
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

    def test_copy_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            src = root / "subdir" / "source.md"
            src.parent.mkdir(parents=True)
            src.write_text("content to copy")
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "add")
            s = Storage(root)
            dst = root / "other" / "dest.md"
            s.copy_file(src, dst)
            self.assertTrue(src.exists())
            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_text(), "content to copy")


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

            owner = NarrativeAddress.from_file_and_annotation(
                "narrative/test/_node.md", operator="section", op_id="ch1"
            )
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

            owner = NarrativeAddress.from_file_and_annotation(
                "narrative/test/ch1/_node.md", operator="write", line=1
            )
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
        self.assertIsNotNone(owner)
        assert owner is not None
        self.assertEqual(owner.narrative, "test")
        self.assertEqual(owner.key_path, ())
        self.assertEqual(owner.operator, "section")
        self.assertEqual(owner.op_id, "ch1")

    def test_added_multiline_annotation(self) -> None:
        diff = (
            "diff --git a/narrative/n/_node.md b/narrative/n/_node.md\n"
            "--- a/narrative/n/_node.md\n"
            "+++ b/narrative/n/_node.md\n"
            "@@ -1 +1,4 @@\n"
            " # root\n"
            "+[write\n"
            "+  prompt: hello\n"
            "+]: #\n"
        )
        owner = detect_pending_owner_from_diff(diff)
        self.assertIsNotNone(owner)
        assert owner is not None
        self.assertEqual(owner.narrative, "n")
        self.assertEqual(owner.key_path, ())
        self.assertEqual(owner.operator, "write")
        self.assertEqual(owner.line, 2)

    def test_removed_annotation_mode3(self) -> None:
        diff = (
            "diff --git a/narrative/n/_node.md b/narrative/n/_node.md\n"
            "--- a/narrative/n/_node.md\n"
            "+++ b/narrative/n/_node.md\n"
            "@@ -1,4 +1,2 @@\n"
            " # root\n"
            "-[edit:fix1]: #\n"
            "-old text\n"
            "+new text\n"
        )
        owner = detect_pending_owner_from_diff(diff)
        self.assertIsNotNone(owner)
        assert owner is not None
        self.assertEqual(owner.narrative, "n")
        self.assertEqual(owner.operator, "edit")
        self.assertEqual(owner.op_id, "fix1")

    def test_added_preferred_over_removed(self) -> None:
        diff = (
            "diff --git a/narrative/n/_node.md b/narrative/n/_node.md\n"
            "--- a/narrative/n/_node.md\n"
            "+++ b/narrative/n/_node.md\n"
            "@@ -1,4 +1,4 @@\n"
            " # root\n"
            "-[write\n"
            "+[write\n"
            " ]: #\n"
        )
        owner = detect_pending_owner_from_diff(diff)
        self.assertIsNotNone(owner)
        assert owner is not None
        self.assertEqual(owner.operator, "write")

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

    def test_annotation_in_non_narrative_file_returns_none(self) -> None:
        diff = (
            "diff --git a/knowledge/place/nyc.md b/knowledge/place/nyc.md\n"
            "--- a/knowledge/place/nyc.md\n"
            "+++ b/knowledge/place/nyc.md\n"
            "@@ -1 +1,2 @@\n"
            " content\n"
            "+[write]: #\n"
        )
        self.assertIsNone(detect_pending_owner_from_diff(diff))

    def test_empty_diff_returns_none(self) -> None:
        self.assertIsNone(detect_pending_owner_from_diff(""))

    def test_close_tag_not_detected_as_owner(self) -> None:
        diff = (
            "diff --git a/narrative/n/_node.md b/narrative/n/_node.md\n"
            "--- a/narrative/n/_node.md\n"
            "+++ b/narrative/n/_node.md\n"
            "@@ -3,0 +4,1 @@\n"
            "+[/section:ch1]: #\n"
        )
        self.assertIsNone(detect_pending_owner_from_diff(diff))


class TestTransactionCRUD(unittest.TestCase):
    """Verify that all file operations (create, update, delete, copy, rename)
    can be performed inside a single Storage transaction and that the resulting
    pending_diff / staged_diff correctly reflect the state."""

    def test_full_crud_copy_rename_in_one_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            s = Storage(root)

            # --- Create (write new file) ---
            new_file = root / "docs" / "intro.md"
            s.write_file(new_file, "# Introduction\n")
            self.assertTrue(new_file.exists())

            # --- Create a second file so we can copy and rename it ---
            src_file = root / "docs" / "source.md"
            s.write_file(src_file, "source content\n")

            # All three ops are still unstaged (pending transaction).
            self.assertTrue(s.has_pending())

            # Stage them (commit the transaction / pending checkpoint).
            s.stage_all()
            self.assertFalse(s.has_pending())
            cached = _git(root, "diff", "--cached", "--name-only")
            self.assertIn("docs/intro.md", cached)
            self.assertIn("docs/source.md", cached)

            # Commit so the files are tracked.
            _git(root, "commit", "-m", "add docs")

            # Re-create Storage for a fresh ownership check.
            s2 = Storage(root)

            # --- Update (overwrite tracked file) ---
            s2.write_file(new_file, "# Introduction\n\nUpdated content.\n")

            # --- Copy ---
            copy_dst = root / "docs" / "copy.md"
            s2.copy_file(src_file, copy_dst)

            # --- Rename (move) ---
            rename_dst = root / "docs" / "renamed.md"
            s2.rename(src_file, rename_dst)

            # src_file gone, copy and renamed exist
            self.assertFalse(src_file.exists())
            self.assertTrue(copy_dst.exists())
            self.assertTrue(rename_dst.exists())
            self.assertEqual(copy_dst.read_text(), "source content\n")
            self.assertEqual(rename_dst.read_text(), "source content\n")

            # pending_diff must include the tracked modification AND the
            # untracked new files (copy + renamed).
            diff = s2.pending_diff()
            self.assertIn("Updated content", diff)
            self.assertIn("docs/copy.md", diff)
            self.assertIn("docs/renamed.md", diff)

            # staged_diff is empty (nothing staged yet in this transaction).
            self.assertEqual(s2.staged_diff(), "")

            # --- Delete ---
            s2.delete_file(copy_dst)
            self.assertFalse(copy_dst.exists())

            # Stage and verify staged_diff is populated.
            s2.stage_all()
            staged = s2.staged_diff()
            self.assertIn("intro.md", staged)
            # pending_diff is now empty (everything staged).
            self.assertEqual(s2.pending_diff(), "")


class TestDetectPendingOwner(unittest.TestCase):
    """Integration tests for Storage.detect_pending_owner().

    These tests cover the untracked-file fallback path that arises when an
    operator creates entirely new files (e.g. section promoting a leaf node to
    a folder), so no annotation appears in git diff.
    """

    def test_tracked_change_detected_via_diff(self) -> None:
        """Annotation added to an existing tracked file is found via diff."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            node = root / "narrative" / "test" / "_node.md"
            node.parent.mkdir(parents=True)
            node.write_text("# test\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "track")

            node.write_text("# test\n\n[section:ch1]: #\n")

            s = Storage(root)
            owner = s.detect_pending_owner()
            self.assertIsNotNone(owner)
            assert owner is not None
            self.assertEqual(owner.operator, "section")
            self.assertEqual(owner.op_id, "ch1")

    def test_untracked_file_fallback(self) -> None:
        """Annotation in an untracked file is found when diff is empty.

        Mirrors the section-operator leaf-to-folder promotion: the original
        leaf .md is deleted (tracked change with no annotation) and the new
        subtree lives entirely in untracked files.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            leaf = root / "narrative" / "test" / "morning.md"
            leaf.parent.mkdir(parents=True)
            leaf.write_text("Some prose.\n")
            _git(root, "add", "-A")
            _git(root, "commit", "-m", "track leaf")

            # Simulate leaf-to-folder promotion: delete the tracked leaf,
            # create the new folder subtree as untracked files.
            leaf.unlink()
            folder = root / "narrative" / "test" / "morning"
            folder.mkdir()
            (folder / "_node.md").write_text("Some prose.\n\n[section:coffee]: #\n")
            (folder / "coffee.md").write_text("")

            s = Storage(root)
            # git diff only sees the deletion of morning.md (no annotation),
            # so detect_pending_owner must fall back to scanning untracked files.
            self.assertIsNone(detect_pending_owner_from_diff(s.diff()))
            owner = s.detect_pending_owner()
            self.assertIsNotNone(owner)
            assert owner is not None
            self.assertEqual(owner.operator, "section")
            self.assertEqual(owner.op_id, "coffee")

    def test_no_pending_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            s = Storage(root)
            self.assertIsNone(s.detect_pending_owner())


def _init_repo_with_upstream(tmp: Path) -> tuple[Path, Path]:
    """Local clone with origin pointing at a bare remote; branch tracks origin/main."""
    bare = tmp / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )
    local = tmp / "local"
    local.mkdir()
    root = _init_repo(local)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "HEAD:main"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return root, bare


class TestRefreshFastForward(unittest.TestCase):
    def test_no_op_when_up_to_date_with_dirty_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root, _bare = _init_repo_with_upstream(Path(tmpdir))
            (root / ".gitkeep").write_text("dirty")
            Storage(root).refresh_fast_forward()

    def test_fails_when_remote_ahead_with_dirty_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            root, bare = _init_repo_with_upstream(tmp)
            (root / ".gitkeep").write_text("dirty")
            subprocess.run(
                ["git", "clone", "-b", "main", str(bare), str(tmp / "other")],
                capture_output=True,
                check=True,
            )
            other = tmp / "other"
            (other / ".gitkeep").write_text("remote change")
            subprocess.run(["git", "add", "-A"], cwd=other, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "ahead"],
                cwd=other,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=other,
                capture_output=True,
                check=True,
            )
            with self.assertRaisesRegex(LensException, "uncommitted changes"):
                Storage(root).refresh_fast_forward()
