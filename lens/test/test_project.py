"""Unit tests for project root discovery and config helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.project import (
    find_project_root_if_any,
    get_selected_datasets,
    is_dataset_root,
)


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


class TestIsDatasetRoot(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_lens_toml_returns_false(self) -> None:
        self.assertFalse(is_dataset_root(self.root))

    def test_dataset_section_returns_true(self) -> None:
        (self.root / "lens.toml").write_text("[dataset]\n")
        self.assertTrue(is_dataset_root(self.root))

    def test_project_only_returns_false(self) -> None:
        (self.root / "lens.toml").write_text("[project]\nnarrative = \"x\"\n")
        self.assertFalse(is_dataset_root(self.root))

    def test_both_sections_with_dataset_returns_true(self) -> None:
        (self.root / "lens.toml").write_text("[dataset]\n[project]\n")
        self.assertTrue(is_dataset_root(self.root))


class TestFindProjectRootIfAny(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_lens_toml_returns_none(self) -> None:
        self.assertIsNone(find_project_root_if_any(self.root))

    def test_finds_nearest_lens_toml(self) -> None:
        (self.root / "lens.toml").write_text("[project]\n")
        sub = self.root / "a" / "b"
        sub.mkdir(parents=True)
        found = find_project_root_if_any(sub)
        assert found is not None
        self.assertEqual(found.resolve(), self.root.resolve())

    def test_nested_project_finds_inner(self) -> None:
        (self.root / "lens.toml").write_text("[project]\n")
        inner = self.root / "nested"
        inner.mkdir()
        (inner / "lens.toml").write_text("[dataset]\n")
        found = find_project_root_if_any(inner)
        assert found is not None
        self.assertEqual(found.resolve(), inner.resolve())
