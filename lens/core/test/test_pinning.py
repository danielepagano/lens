"""Unit tests for lens.pinning: front matter pin/unpin manipulation."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.annotations import parse_front_matter
from lens.core.narrative import NarrativeNode
from lens.core.pinning import (
    KB_PIN,
    KB_UNPIN,
    pin,
    remove_pin,
    remove_unpin,
    set_param,
    set_var,
    unpin,
    unset_param,
    unset_var,
)
from lens.core.storage import Storage


def init_git_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def make_pin_test_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp, capture_output=True, check=True,
    )
    node = NarrativeNode(narrative_root=narrative_dir, key_path=())
    return tmp, node


class TestPin(unittest.TestCase):
    def test_creates_front_matter_when_none_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            pin(node, ["place.needle_street"], storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get(KB_PIN), ["place.needle_street"])

    def test_appends_to_existing_kb_pin_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            md = node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.a\n]: #\n\n# test\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            storage = Storage(root, owner=None)
            pin(node, ["place.b"], storage)
            fm = parse_front_matter(md.read_text())
            self.assertEqual(fm.get(KB_PIN), ["place.a", "place.b"])

    def test_idempotent_no_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            pin(node, ["place.x", "place.y"], storage)
            pin(node, ["place.x"], storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get(KB_PIN), ["place.x", "place.y"])


class TestUnpin(unittest.TestCase):
    def test_creates_kb_unpin_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            unpin(node, ["front.the_demon_rises"], storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get(KB_UNPIN), ["front.the_demon_rises"])


class TestRemovePin(unittest.TestCase):
    def test_removes_pin_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            pin(node, ["place.a", "place.b", "place.c"], storage)
            remove_pin(node, ["place.b"], storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get(KB_PIN), ["place.a", "place.c"])

    def test_remove_last_pin_cleans_up_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            pin(node, ["place.only"], storage)
            remove_pin(node, ["place.only"], storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertNotIn(KB_PIN, fm)

    def test_empty_dict_removes_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            pin(node, ["place.only"], storage)
            self.assertIn("[", node.md_path().read_text())
            remove_pin(node, ["place.only"], storage)
            text = node.md_path().read_text()
            self.assertNotIn("kb_pin", text)
            self.assertNotIn("[\n", text)


class TestRemoveUnpin(unittest.TestCase):
    def test_removes_unpin_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            unpin(node, ["a.x", "b.y", "c.z"], storage)
            remove_unpin(node, ["b.y"], storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get(KB_UNPIN), ["a.x", "c.z"])

    def test_remove_last_unpin_cleans_up_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            unpin(node, ["x.only"], storage)
            remove_unpin(node, ["x.only"], storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertNotIn(KB_UNPIN, fm)


class TestFrontMatterPreserved(unittest.TestCase):
    def test_only_one_key_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            md = node.md_path()
            md.write_text(
                "[\n  kb_pin:\n    - place.a\n  kb_unpin:\n    - front.x\n]: #\n\n# test\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            storage = Storage(root, owner=None)
            pin(node, ["place.b"], storage)
            fm = parse_front_matter(md.read_text())
            self.assertEqual(fm.get(KB_PIN), ["place.a", "place.b"])
            self.assertEqual(fm.get(KB_UNPIN), ["front.x"])


class TestVarPin(unittest.TestCase):
    def test_set_var_creates_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            set_var(node, "mood", "dark", storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get("vars"), {"mood": "dark"})

    def test_unset_var_removes_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            md = node.md_path()
            md.write_text("[\n  vars:\n    mood: x\n    color: y\n]: #\n\n# test\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            storage = Storage(root, owner=None)
            unset_var(node, "mood", storage)
            fm = parse_front_matter(md.read_text())
            self.assertEqual(fm.get("vars"), {"color": "y"})

    def test_unset_last_var_removes_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            set_var(node, "only", "v", storage)
            unset_var(node, "only", storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertNotIn("vars", fm)


class TestParamPin(unittest.TestCase):
    def test_set_param_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            set_param(node, "global", "llm_id", "fast", storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get("params"), {"global": {"llm_id": "fast"}})

    def test_set_param_operator_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            set_param(node, "write", "reasoning", True, storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get("params"), {"write": {"reasoning": True}})

    def test_unset_param_removes_scope_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            set_param(node, "global", "a", 1, storage)
            set_param(node, "write", "b", "c", storage)
            unset_param(node, "global", "a", storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertEqual(fm.get("params"), {"write": {"b": "c"}})

    def test_unset_last_param_removes_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            storage = Storage(root, owner=None)
            set_param(node, "global", "x", "y", storage)
            unset_param(node, "global", "x", storage)
            fm = parse_front_matter(node.md_path().read_text())
            self.assertNotIn("params", fm)


class TestPinDoesNotAffectContent(unittest.TestCase):
    def test_non_front_matter_content_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = make_pin_test_project(init_git_repo(Path(tmp)))
            md = node.md_path()
            original = "# test\n\nSome prose here.\n\nAnd more."
            md.write_text(original)
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "content"], cwd=root, capture_output=True, check=True)
            storage = Storage(root, owner=None)
            pin(node, ["place.x"], storage)
            text = md.read_text()
            self.assertIn("Some prose here.", text)
            self.assertIn("And more.", text)
