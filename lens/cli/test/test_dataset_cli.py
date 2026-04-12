"""Tests for dataset mode: allowed commands and blocked commands."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_LENS_CMD = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]


def _make_dataset_in_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    dataset_dir = tmp / "mydataset"
    dataset_dir.mkdir()
    (dataset_dir / "lens.toml").write_text("[dataset]\n")
    (dataset_dir / "knowledge").mkdir()
    (dataset_dir / "knowledge" / "person").mkdir()
    (dataset_dir / "knowledge" / "person" / "hero.md").write_text("A hero.")
    (dataset_dir / "knowledge" / "tags.toml").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "dataset"], cwd=tmp, capture_output=True, check=True)
    return dataset_dir


class TestDatasetCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.dataset_dir = _make_dataset_in_repo(self.root)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stats_works(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["stats"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Dataset: mydataset", result.stdout)
        self.assertIn("Knowledge Store", result.stdout)
        self.assertNotIn("Narrative trees", result.stdout)
        self.assertNotIn("Active narrative cursor", result.stdout)

    def test_stats_verbose_works(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["stats", "--verbose"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Dataset: mydataset", result.stdout)

    def test_kb_works(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["kb", "get", "person.hero"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("A hero.", result.stdout)

    def test_commit_works(self) -> None:
        (self.dataset_dir / "knowledge" / "person" / "new.md").write_text("New.")
        result = subprocess.run(
            _LENS_CMD + ["commit"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Staged", result.stdout)

    def test_rollback_works(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["rollback"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("No pending", result.stdout)

    def test_init_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["init"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("datasets don't use init", result.stderr)

    def test_use_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["use", "story"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("datasets don't use init/use", result.stderr)

    def test_checkpoint_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["checkpoint"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("checkpoint is not available in dataset mode", result.stderr)

    def test_pin_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["pin", "add", "person.hero"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("pin is not available in dataset mode", result.stderr)

    def test_section_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["section", "ch1"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("section is not available in dataset mode", result.stderr)

    def test_collate_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["collate", "ch1", "/story", "1", "5"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("collate is not available in dataset mode", result.stderr)

    def test_compress_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["compress", "anything"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("compress is not available in dataset mode", result.stderr)

    def test_write_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["write", "continue"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("write is not available in dataset mode", result.stderr)

    def test_edit_blocked(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["edit", "/x", "1", "5", "fix"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("edit is not available in dataset mode", result.stderr)


class TestKbEditCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.dataset_dir = _make_dataset_in_repo(self.root)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_edit_help(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["kb", "edit", "--help"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        out = result.stdout
        self.assertIn("--context", out)
        self.assertIn("--pin", out)
        self.assertIn("--unpin", out)
        self.assertIn("--include-template", out)
        self.assertIn("--llm", out)

    def test_edit_missing_args_shows_help(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["kb", "edit"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("edit", result.stdout + result.stderr)

    def test_edit_dataset_mode_context_rejected(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["kb", "edit", "person.hero", "update", "--context", "/foo"],
            cwd=self.dataset_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not available in dataset mode", result.stderr)
