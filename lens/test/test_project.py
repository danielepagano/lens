"""Unit tests for project root discovery and config helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.project import get_selected_datasets


class TestGetSelectedDatasets(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_lens_toml_returns_empty(self) -> None:
        self.assertEqual(get_selected_datasets(self.root), [])

    def test_empty_project_section_returns_empty(self) -> None:
        (self.root / "lens.toml").write_text("[project]\n")
        self.assertEqual(get_selected_datasets(self.root), [])

    def test_datasets_not_set_returns_empty(self) -> None:
        (self.root / "lens.toml").write_text("[project]\nnarrative = \"story\"\n")
        self.assertEqual(get_selected_datasets(self.root), [])

    def test_datasets_list_returns_names(self) -> None:
        (self.root / "lens.toml").write_text(
            "[project]\n"
            "narrative = \"story\"\n"
            "datasets = [\"testing\", \"extra\"]\n"
        )
        self.assertEqual(get_selected_datasets(self.root), ["testing", "extra"])

    def test_datasets_single_returns_list(self) -> None:
        (self.root / "lens.toml").write_text("[project]\ndatasets = [\"testing\"]\n")
        self.assertEqual(get_selected_datasets(self.root), ["testing"])

    def test_datasets_non_list_returns_empty(self) -> None:
        (self.root / "lens.toml").write_text("[project]\ndatasets = \"testing\"\n")
        self.assertEqual(get_selected_datasets(self.root), [])

    def test_datasets_filters_non_strings(self) -> None:
        (self.root / "lens.toml").write_text(
            "[project]\n"
            "datasets = [\"valid\", 42, true, \"also_valid\"]\n"
        )
        self.assertEqual(get_selected_datasets(self.root), ["valid", "also_valid"])
