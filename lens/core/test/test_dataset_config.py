"""Tests for dataset-specific project configuration."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.dataset_config import (
    clear_dataset_configs_for_tests,
    get_dataset_configs,
    register_dataset_config,
)


def _git_init(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )


def _write_project(root: Path, datasets: list[str], extra_toml: str = "") -> None:
    ds = ", ".join(f'"{d}"' for d in datasets)
    (root / "lens.toml").write_text(
        f'[project]\nnarrative = "story"\ndatasets = [{ds}]\n'
        '[[llm]]\nbase_url = "http://127.0.0.1:1"\nmodel = "x"\n'
        f"{extra_toml}\n",
        encoding="utf-8",
    )
    (root / "narrative").mkdir(exist_ok=True)
    (root / "narrative" / "story").mkdir(exist_ok=True)
    (root / "narrative" / "story" / "_node.md").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)


class TestDatasetConfig(unittest.TestCase):
    def setUp(self) -> None:
        clear_dataset_configs_for_tests()
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _git_init(self.root)

    def tearDown(self) -> None:
        clear_dataset_configs_for_tests()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_register_and_return_defaults(self) -> None:
        register_dataset_config("myds", {"key1": "val1", "key2": "val2"})
        _write_project(self.root, ["myds"])
        configs = get_dataset_configs(self.root)
        self.assertIn("myds", configs)
        self.assertEqual(configs["myds"]["key1"], "val1")
        self.assertEqual(configs["myds"]["key2"], "val2")

    def test_override_from_project_toml(self) -> None:
        register_dataset_config("myds", {"key1": "default", "key2": "default"})
        extra = '[config-myds]\nkey1 = "overridden"\n'
        _write_project(self.root, ["myds"], extra_toml=extra)
        configs = get_dataset_configs(self.root)
        self.assertEqual(configs["myds"]["key1"], "overridden")
        self.assertEqual(configs["myds"]["key2"], "default")

    def test_unregistered_key_override_ignored(self) -> None:
        register_dataset_config("myds", {"known": "val"})
        extra = '[config-myds]\nknown = "new"\nunknown = "ignored"\n'
        _write_project(self.root, ["myds"], extra_toml=extra)
        configs = get_dataset_configs(self.root)
        self.assertEqual(configs["myds"]["known"], "new")
        self.assertNotIn("unknown", configs["myds"])

    def test_none_for_non_selected_dataset(self) -> None:
        register_dataset_config("myds", {"k": "v"})
        _write_project(self.root, ["other"])
        configs = get_dataset_configs(self.root)
        self.assertNotIn("myds", configs)

    def test_does_not_return_unregistered_dataset(self) -> None:
        _write_project(self.root, ["unknown"])
        configs = get_dataset_configs(self.root)
        self.assertNotIn("unknown", configs)

    def test_clear_registry(self) -> None:
        register_dataset_config("myds", {"k": "v"})
        clear_dataset_configs_for_tests()
        _write_project(self.root, ["myds"])
        configs = get_dataset_configs(self.root)
        self.assertNotIn("myds", configs)
