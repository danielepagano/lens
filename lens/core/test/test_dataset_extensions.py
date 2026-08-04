"""Tests for dataset extension loading (manifest + sys.path)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lens.core.command_tools import (
    _REGISTRY as _CMD_REGISTRY,  # pyright: ignore[reportPrivateUsage]
    get_command_registry,
)
from lens.core.dataset_extensions import (
    clear_extension_state_for_tests,
    ensure_dataset_extensions,
    get_extension_commands,
    read_dataset_extension,
)
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.prompts import PromptStore, tool_prompt_key

_LENS_CMD = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]


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


def _write_project(root: Path, datasets: list[str]) -> None:
    ds = ", ".join(f'"{d}"' for d in datasets)
    (root / "lens.toml").write_text(
        f'[project]\nnarrative = "story"\ndatasets = [{ds}]\n'
        '[[llm]]\nbase_url = "http://127.0.0.1:1"\nmodel = "x"\n',
        encoding="utf-8",
    )
    (root / "narrative").mkdir(exist_ok=True)
    (root / "narrative" / "story").mkdir(exist_ok=True)
    (root / "narrative" / "story" / "_node.md").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)


class TestDatasetExtensions(unittest.TestCase):
    def setUp(self) -> None:
        clear_extension_state_for_tests()
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _git_init(self.root)
        _write_project(self.root, ["testing"])

    def tearDown(self) -> None:
        clear_extension_state_for_tests()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_read_extension_from_testing_dataset(self) -> None:
        from lens.core.project import datasets_root

        spec = read_dataset_extension(datasets_root() / "testing")
        self.assertEqual(spec, "lens_testing_ext")

    def test_ensure_loads_extension_commands(self) -> None:
        ensure_dataset_extensions(self.root)
        names = [n for n, _ in get_extension_commands()]
        self.assertIn("testing-ext", names)

    def test_testing_ext_tool_in_registry(self) -> None:
        registry = get_command_registry(self.root)
        self.assertIn("testing_ext", registry)

    def test_testing_ext_tool_excluded_without_dataset(self) -> None:
        other = Path(self.tmp) / "other"
        other.mkdir()
        _git_init(other)
        _write_project(other, [])
        registry = get_command_registry(other)
        self.assertNotIn("testing_ext", registry)

    def test_dataset_prompts_merged(self) -> None:
        store = PromptStore(self.root)
        key = tool_prompt_key("testing_ext")
        self.assertIn("Testing extension tool", store.get(key))

    def test_cli_extension_subcommand(self) -> None:
        result = subprocess.run(
            _LENS_CMD + ["testing-ext", "ping"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pong", result.stdout)

    def test_idempotent_load(self) -> None:
        ensure_dataset_extensions(self.root)
        ensure_dataset_extensions(self.root)
        self.assertEqual(len(get_extension_commands()), 1)

    def test_testing_ext_tool_registered_once(self) -> None:
        ensure_dataset_extensions(self.root)
        self.assertIn("testing_ext", _CMD_REGISTRY)
