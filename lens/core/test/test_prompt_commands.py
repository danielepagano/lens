"""Unit tests for prompt command helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.prompt import prompt_get, prompt_set


class TestPromptCommands(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "lens.toml").write_text("[project]\nnarrative = \"story\"\n", encoding="utf-8")
        self.old_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        import shutil

        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prompt_set_then_get_reads_project_override(self) -> None:
        prompt_set("write.system", "OVERRIDDEN WRITE")
        record = prompt_get("write.system")
        self.assertEqual(record.source, "project")
        self.assertEqual(record.value, "OVERRIDDEN WRITE")
