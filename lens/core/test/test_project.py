"""Unit tests for project root discovery and config helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lens.core.project import (
    read_local_dataset_paths,
    find_project_root_if_any,
    get_selected_prompt_pack,
    get_selected_datasets,
    is_dataset_root,
    resolve_dataset_path,
    set_selected_prompt_pack,
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


class TestPromptPackSelection(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "lens.toml").write_text("[project]\nnarrative = \"story\"\n", encoding="utf-8")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_selected_prompt_pack_default_none(self) -> None:
        self.assertIsNone(get_selected_prompt_pack(self.root))

    def test_set_selected_prompt_pack(self) -> None:
        set_selected_prompt_pack(self.root, "it")
        self.assertEqual(get_selected_prompt_pack(self.root), "it")

    def test_clear_selected_prompt_pack(self) -> None:
        set_selected_prompt_pack(self.root, "it")
        set_selected_prompt_pack(self.root, None)
        self.assertIsNone(get_selected_prompt_pack(self.root))


class TestReadLocalDatasetPaths(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_file_returns_empty(self) -> None:
        self.assertEqual(read_local_dataset_paths(self.root), {})

    def test_parses_dataset_paths(self) -> None:
        (self.root / "lens.local.toml").write_text(
            '[dataset_paths]\ndnd = "/code/dnd"\n'
        )
        result = read_local_dataset_paths(self.root)
        self.assertEqual(result, {"dnd": "/code/dnd"})

    def test_ignores_non_string_values(self) -> None:
        (self.root / "lens.local.toml").write_text(
            '[dataset_paths]\ngood = "/code/good"\nbad = 42\n'
        )
        result = read_local_dataset_paths(self.root)
        self.assertEqual(result, {"good": "/code/good"})

    def test_missing_section_returns_empty(self) -> None:
        (self.root / "lens.local.toml").write_text("[other]\nfoo = 1\n")
        self.assertEqual(read_local_dataset_paths(self.root), {})


class TestResolveDatasetPath(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.project = Path(self.tmp) / "project"
        self.project.mkdir()
        (self.project / "lens.toml").write_text("[project]\n")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bundled_dataset_found(self) -> None:
        # rpg and testing are bundled with lens
        result = resolve_dataset_path(self.project, "rpg")
        self.assertIsNotNone(result)
        self.assertTrue(result.is_dir())  # type: ignore[union-attr]

    def test_nonexistent_returns_none(self) -> None:
        result = resolve_dataset_path(self.project, "does-not-exist-xyz")
        self.assertIsNone(result)

    def test_local_override_absolute(self) -> None:
        ds_dir = Path(self.tmp) / "my-dataset"
        ds_dir.mkdir()
        (ds_dir / "lens.toml").write_text("[dataset]\n")
        (ds_dir / "knowledge").mkdir()
        (self.project / "lens.local.toml").write_text(
            f'[dataset_paths]\nmy-dataset = "{ds_dir}"\n'
        )
        result = resolve_dataset_path(self.project, "my-dataset")
        self.assertIsNotNone(result)
        self.assertEqual(result.resolve(), ds_dir.resolve())  # type: ignore[union-attr]

    def test_local_override_relative(self) -> None:
        ds_dir = Path(self.tmp) / "rel-dataset"
        ds_dir.mkdir()
        (ds_dir / "knowledge").mkdir()
        (self.project / "lens.local.toml").write_text(
            '[dataset_paths]\nrel-dataset = "../rel-dataset"\n'
        )
        result = resolve_dataset_path(self.project, "rel-dataset")
        self.assertIsNotNone(result)
        self.assertEqual(result.resolve(), ds_dir.resolve())  # type: ignore[union-attr]

    def test_sibling_of_lens_repo(self) -> None:
        # Create a directory that is a sibling of the lens repo root
        from lens.core.project import datasets_root
        lens_repo_root = datasets_root().parent
        sibling = lens_repo_root.parent / "test-sibling-dataset-xyz"
        created = False
        try:
            sibling.mkdir(exist_ok=True)
            created = True
            result = resolve_dataset_path(self.project, "test-sibling-dataset-xyz")
            self.assertIsNotNone(result)
            self.assertEqual(result.resolve(), sibling.resolve())  # type: ignore[union-attr]
        finally:
            if created and sibling.exists():
                sibling.rmdir()
