"""Unit tests for shared storage text normalization and cache behavior."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.storage import Storage
from lens.core.storage_text import (
    StorageTextNormalizer,
    format_kb_prompt_block,
    normalize_storage_text,
)


def _init_repo(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )


class TestNormalizeStorageText(unittest.TestCase):
    def test_builds_strip_and_llm_views(self) -> None:
        raw = "one\n[ aside ]: #\n<!-- ai:secret: uryyb -->\nthree\n"
        normalized = normalize_storage_text(raw)
        self.assertEqual(
            normalized.strip_comments_text, "one\n<!-- ai:secret: uryyb -->\nthree\n"
        )
        self.assertEqual(
            normalized.llm_view.visible_for_llm,
            "one\n<!-- ai:secret:\nhello\n-->\nthree\n",
        )
        self.assertEqual(normalized.llm_view.disk_line_start_1based, (1, 3, 3, 3, 4))
        self.assertEqual(normalized.llm_view.disk_line_end_1based, (1, 3, 3, 3, 4))

    def test_formats_kb_prompt_block(self) -> None:
        out = format_kb_prompt_block(
            canonical_id="person.alice",
            text="Visible\n[meta]: #\n",
            tags=["hero", "pc"],
            include_comments=False,
        )
        self.assertEqual(out, "KB['person.alice']  TAGS=hero, pc\nVisible\n")


class TestStorageTextNormalizer(unittest.TestCase):
    def test_path_cache_updates_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            md = base / "doc.md"
            md.write_text("A\n", encoding="utf-8")
            normalizer = StorageTextNormalizer()
            first = normalizer.normalize_path(md)
            second = normalizer.normalize_path(md)
            self.assertIs(first, second)

            md.write_text("B\n", encoding="utf-8")
            third = normalizer.normalize_path(md)
            self.assertEqual(third.llm_visible_text, "B\n")
            self.assertNotEqual(first.llm_visible_text, third.llm_visible_text)

    def test_raw_cache_uses_source_id(self) -> None:
        normalizer = StorageTextNormalizer()
        first = normalizer.normalize_raw("A\n", source_id="x")
        second = normalizer.normalize_raw("A\n", source_id="x")
        self.assertIs(first, second)
        third = normalizer.normalize_raw("B\n", source_id="x")
        self.assertEqual(third.llm_visible_text, "B\n")


class TestStorageNormalizationInvalidation(unittest.TestCase):
    def test_storage_write_invalidates_path_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            md = root / "note.md"
            md.write_text("before\n", encoding="utf-8")
            storage = Storage(root)

            first = storage.normalize_path_text(md)
            storage.write_file(md, "after\n")
            second = storage.normalize_path_text(md)

            self.assertEqual(first.llm_visible_text, "before\n")
            self.assertEqual(second.llm_visible_text, "after\n")

