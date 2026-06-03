"""Tests for companion-aware narrative creation via ``use_narrative_for_project``."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.use import use_narrative_for_project
from lens.core.exceptions import LensException


def _init_repo(tmp: Path) -> None:
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
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )


def _write_minimal_project(
    root: Path,
    *,
    narrative_slug: str,
    datasets: list[str],
) -> None:
    ds_toml = (
        "datasets = ["
        + ", ".join(f'"{d}"' for d in datasets)
        + "]\n"
        if datasets
        else ""
    )
    (root / "lens.toml").write_text(
        f'[project]\nnarrative = "{narrative_slug}"\n{ds_toml}',
        encoding="utf-8",
    )
    (root / "knowledge").mkdir()
    (root / "knowledge" / "tags.toml").write_text("{}", encoding="utf-8")
    (root / "narrative" / narrative_slug).mkdir(parents=True)
    (root / "narrative" / narrative_slug / "_node.md").write_text(
        f"# {narrative_slug}\n", encoding="utf-8"
    )


class TestUseCompanionNarrative(unittest.TestCase):
    def test_companion_chat_sets_params_and_kb_stubs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _write_minimal_project(root, narrative_slug="seed", datasets=["companion"])
            hint = use_narrative_for_project(
                "c1",
                root,
                root,
                narrative_kind="companion_chat",
                companion_as_kb_id="companion.mara",
                companion_with_kb_id="human.adam",
            )
            self.assertIsNotNone(hint)
            node = root / "narrative" / "c1" / "_node.md"
            text = node.read_text(encoding="utf-8")
            self.assertIn("kb_pin:", text)
            self.assertIn("companion.mara+", text)
            self.assertIn("human.adam+", text)
            self.assertIn("as_kb_id:", text)
            self.assertIn("companion.mara", text)
            self.assertIn("with_kb_id:", text)
            self.assertIn("human.adam", text)
            self.assertIn("# Mara & Adam", text)
            self.assertTrue((root / "knowledge" / "companion" / "mara.md").is_file())
            self.assertTrue((root / "knowledge" / "human" / "adam.md").is_file())

    def test_requires_companion_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _write_minimal_project(root, narrative_slug="seed", datasets=["testing"])
            with self.assertRaises(LensException):
                use_narrative_for_project(
                    "c1",
                    root,
                    root,
                    narrative_kind="companion_chat",
                    companion_as_kb_id="companion.mara",
                    companion_with_kb_id="human.adam",
                )

    def test_rejects_non_companion_as_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _write_minimal_project(root, narrative_slug="seed", datasets=["companion"])
            with self.assertRaises(LensException):
                use_narrative_for_project(
                    "c1",
                    root,
                    root,
                    narrative_kind="companion_chat",
                    companion_as_kb_id="person.mara",
                    companion_with_kb_id="human.adam",
                )
