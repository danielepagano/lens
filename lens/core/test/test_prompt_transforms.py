"""Unit tests for prompt transform registry (@-tokens, vars, rolls)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import collect_vars
from lens.core.dice import DiceError
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.prompt_transforms import (
    PromptTransformContext,
    PromptTransformTarget,
    transform_prompt,
)
from lens.core.narrative import NarrativeNode
from lens.core.storage import Storage


def _init_repo(tmp: Path) -> Path:
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
    return tmp


def _make_narrative(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "narrative"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


def _add_kb(root: Path, type_name: str, key: str, content: str) -> None:
    path = root / "knowledge" / type_name / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"kb {type_name}.{key}"],
        cwd=root,
        capture_output=True,
        check=True,
    )


def _ctx(root: Path, storage: Storage, node: NarrativeNode | None = None) -> PromptTransformContext:
    return PromptTransformContext(
        project_root=root, storage=storage, cursor=node
    )


class TestTransformPromptStorable(unittest.TestCase):
    def test_expands_var_and_roll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _root_node = _make_narrative(_init_repo(Path(tmp)))
            story = root / "narrative" / "test"
            md = story / "scene.md"
            md.write_text(
                "[\n  vars:\n    mood: dark\n]: #\n\n# Scene\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "scene"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            node = NarrativeNode(narrative_root=story, key_path=("scene",))
            storage = Storage(root)
            out = transform_prompt(
                "Feel @var:mood — @roll d20 check",
                _ctx(root, storage, node),
                target=PromptTransformTarget.STORABLE,
            )
            self.assertIn("dark", out)
            self.assertIn("rolled d20=", out)
            self.assertNotIn("@var:mood", out)
            self.assertNotIn("@roll", out)

    def test_inline_kb_baked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _root_node = _make_narrative(_init_repo(Path(tmp)))
            _add_kb(root, "visual", "amy", "red hair")
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("visual.amy", ["inline"])
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "tag inline"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            story = root / "narrative" / "test"
            md = story / "opening.md"
            md.write_text("# x\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "opening"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            node = NarrativeNode(narrative_root=story, key_path=("opening",))
            storage = Storage(root)
            out = transform_prompt(
                "@visual.amy waves",
                _ctx(root, storage, node),
                target=PromptTransformTarget.STORABLE,
            )
            self.assertIn("red hair waves", out)
            self.assertNotIn("@visual.amy", out)

    def test_dice_error_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _root_node = _make_narrative(_init_repo(Path(tmp)))
            story = root / "narrative" / "test"
            (story / "opening.md").write_text("# x\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "opening"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            node = NarrativeNode(narrative_root=story, key_path=("opening",))
            with self.assertRaises(DiceError):
                transform_prompt(
                    "@roll XYZZY",
                    _ctx(root, Storage(root), node),
                    target=PromptTransformTarget.STORABLE,
                )


class TestTransformPromptFlat(unittest.TestCase):
    def test_force_inline_kb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _make_narrative(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "silver cloak")
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            storage = Storage(root)
            out = transform_prompt(
                "@person.amy at dusk",
                _ctx(root, storage),
                target=PromptTransformTarget.FLAT,
            )
            self.assertIn("silver cloak at dusk", out)
            self.assertNotIn("@person.amy", out)

    def test_no_at_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _make_narrative(_init_repo(Path(tmp)))
            storage = Storage(root)
            self.assertEqual(
                transform_prompt(
                    "plain prompt",
                    _ctx(root, storage),
                    target=PromptTransformTarget.FLAT,
                ),
                "plain prompt",
            )


class TestCollectVarsUsedByPersist(unittest.TestCase):
    def test_inherited_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _make_narrative(_init_repo(Path(tmp)))
            story = root / "narrative" / "test"
            (story / "opening.md").write_text(
                "[\n  vars:\n    tone: grim\n]: #\n\n# x\n",
                encoding="utf-8",
            )
            node = NarrativeNode(narrative_root=story, key_path=("opening",))
            self.assertEqual(collect_vars(node)["tone"], "grim")
