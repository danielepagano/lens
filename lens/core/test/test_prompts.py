"""Unit tests for prompt store resolution and copy-on-write overrides."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.prompts import PromptStore, project_prompts_file


class TestPromptStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "lens.toml").write_text("[project]\nnarrative = \"story\"\n", encoding="utf-8")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_builtin_resolution(self) -> None:
        store = PromptStore(self.root)
        resolved = store.resolve("write.system")
        self.assertEqual(resolved.source, "builtin")
        self.assertIn("story-writing assistant", resolved.value)

    def test_project_override_wins(self) -> None:
        store = PromptStore(self.root)
        store.set_project_override("write.system", "PROJECT WRITE")

        fresh = PromptStore(self.root)
        resolved = fresh.resolve("write.system")
        self.assertEqual(resolved.source, "project")
        self.assertEqual(resolved.value, "PROJECT WRITE")

    def test_clear_project_override_reveals_builtin(self) -> None:
        store = PromptStore(self.root)
        store.set_project_override("write.system", "PROJECT WRITE")
        store.clear_project_override("write.system")

        fresh = PromptStore(self.root)
        resolved = fresh.resolve("write.system")
        self.assertEqual(resolved.source, "builtin")

    def test_project_override_file_created(self) -> None:
        store = PromptStore(self.root)
        store.set_project_override("write.system", "PROJECT WRITE")
        path = project_prompts_file(self.root)
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("[prompts]", text)
        self.assertIn("write.system", text)
