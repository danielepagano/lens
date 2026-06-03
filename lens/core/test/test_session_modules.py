from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import crawl, session_module_ids
from lens.core.narrative import NarrativeNode
from lens.core.operators.design import DesignOperator
from lens.core.storage import Storage
from lens.rpg.operators.play import PlayOperator


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


def _make_project(tmp: Path, *, datasets: str | None = None) -> tuple[Path, NarrativeNode]:
    ds = f'\ndatasets = [{datasets!r}]' if datasets else ""
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "test"{ds}\n')
    narrative_dir = tmp / "narrative" / "test"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# test\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


def _design_session_child(
    root: Path, parent: NarrativeNode, *, module_key: str
) -> NarrativeNode:
    child_dir = parent.narrative_root / "design-sess"
    child_dir.mkdir(exist_ok=True)
    (child_dir / "_node.md").write_text("# design-sess\n")
    parent.md_path().write_text(
        f"# test\n\n[design:design-sess\n  module: {module_key}\n]: #\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "design session"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return NarrativeNode(narrative_root=parent.narrative_root, key_path=("design-sess",))


class TestSessionModuleIds(unittest.TestCase):
    def test_session_module_ids_from_parent_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, parent = _make_project(_init_repo(Path(tmp)))
            child = _design_session_child(root, parent, module_key="world")
            ids = session_module_ids(
                child, operator_name="design", module_prefix="design."
            )
            self.assertEqual(ids, ("design.world",))


class TestSessionModuleCrawl(unittest.TestCase):
    def test_design_crawl_spec_sets_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, parent = _make_project(_init_repo(Path(tmp)))
            child = _design_session_child(root, parent, module_key="world")
            spec = DesignOperator.crawl_spec(
                child, {}, session=None, narrative=parent, storage=Storage(root)
            )
            self.assertEqual(spec.modules, ("design.world",))

    def test_design_module_kb_in_crawl_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, parent = _make_project(_init_repo(Path(tmp)))
            design_dir = root / "knowledge" / "design"
            design_dir.mkdir(parents=True, exist_ok=True)
            (design_dir / "world.md").write_text("Design world module\n")
            child = _design_session_child(root, parent, module_key="world")
            crawl_result = crawl(
                DesignOperator.crawl_spec(
                    child, {}, session=None, narrative=parent, storage=Storage(root)
                )
            )
            self.assertTrue(
                any("Design world module" in block for block in crawl_result.knowledge),
                crawl_result.knowledge,
            )

    def test_play_crawl_spec_sets_rules_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            rules_dir = root / "knowledge" / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            (rules_dir / "combat.md").write_text("Combat rules module\n")
            _root, parent = _make_project(root, datasets="rpg")
            child_dir = parent.narrative_root / "play-sess"
            child_dir.mkdir(exist_ok=True)
            (child_dir / "_node.md").write_text("# play-sess\n")
            parent.md_path().write_text(
                "# test\n\n[play:play-sess\n  module: combat\n]: #\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "play session"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            child = NarrativeNode(
                narrative_root=parent.narrative_root, key_path=("play-sess",)
            )
            spec = PlayOperator.crawl_spec(
                child, {}, session=None, narrative=parent, storage=Storage(root)
            )
            self.assertEqual(spec.modules, ("rules.combat",))
            crawl_result = crawl(spec)
            self.assertTrue(
                any("Combat rules module" in block for block in crawl_result.knowledge),
                crawl_result.knowledge,
            )
