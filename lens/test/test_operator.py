"""Unit tests for lens.operator: base class, tag builders, and mode helpers."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from lens.narrative import NarrativeNode
from lens.operator import Operator
from lens.storage import Storage


def _init_repo(tmp: Path) -> Path:
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


def _make_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    """Create a minimal lens project with a narrative and commit."""
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


class _TestOp(Operator):
    """Concrete operator for testing."""
    name: ClassVar[str] = "testop"
    requires_id: ClassVar[bool] = True


class _NoIdOp(Operator):
    """Operator that does not require an annotation ID."""
    name: ClassVar[str] = "noid"
    requires_id: ClassVar[bool] = False


# ------------------------------------------------------------------
# Tag builders (pure string operations, verified in a real repo context)
# ------------------------------------------------------------------

class TestTagBuilders(unittest.TestCase):
    def test_open_tag_with_id_no_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = _TestOp(Storage(root, owner="testop:ch1@x"), narrative)
            self.assertEqual(op.build_open_tag("ch1"), "[testop:ch1]: #")

    def test_open_tag_without_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = _TestOp(Storage(root, owner="testop:ch1@x"), narrative)
            self.assertEqual(op.build_open_tag(), "[testop]: #")

    def test_open_tag_with_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = _TestOp(Storage(root, owner="testop:ch1@x"), narrative)
            tag = op.build_open_tag("ch1", {"prompt": "hello"})
            self.assertIn("[testop:ch1", tag)
            self.assertIn("prompt: hello", tag)
            self.assertTrue(tag.endswith("]: #"))

    def test_close_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = _TestOp(Storage(root, owner="testop:ch1@x"), narrative)
            self.assertEqual(op.build_close_tag("ch1"), "[/testop:ch1]: #")

    def test_close_tag_no_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = _TestOp(Storage(root, owner="testop:ch1@x"), narrative)
            self.assertEqual(op.build_close_tag(), "[/testop]: #")

    def test_self_closing_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = _TestOp(Storage(root, owner="testop:ch1@x"), narrative)
            self.assertEqual(op.build_self_closing_tag("notes"), "[testop:notes/]: #")


class TestOwnerIdConstruction(unittest.TestCase):
    def test_with_id(self) -> None:
        oid = _TestOp.owner_id("ch1", "narrative/test/_node.md")
        self.assertEqual(oid, "testop:ch1@narrative/test/_node.md")

    def test_without_id_with_line(self) -> None:
        oid = _NoIdOp.owner_id(None, "narrative/test/_node.md", 5)
        self.assertEqual(oid, "noid@narrative/test/_node.md:5")


# ------------------------------------------------------------------
# Annotation reading
# ------------------------------------------------------------------

class TestAnnotationReading(unittest.TestCase):
    def test_find_my_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = _TestOp(Storage(root, owner="testop:ch1@x"), narrative)
            text = "[testop:ch1]: #\nbody\n\n[/testop:ch1]: #\n[section:x]: #\n"
            anns = op.find_my_annotations(text)
            self.assertEqual(len(anns), 2)
            self.assertEqual(anns[0].operator, "testop")

    def test_find_my_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = _TestOp(Storage(root, owner="testop:ch1@x"), narrative)
            text = "[testop:ch1]: #\nbody\n\n[/testop:ch1]: #\n"
            segs = op.find_my_segments(text)
            self.assertEqual(len(segs), 1)
            assert segs[0].annotation is not None
            self.assertEqual(segs[0].annotation.operator, "testop")
            self.assertEqual(segs[0].body.strip(), "body")


# ------------------------------------------------------------------
# Mode 2: sub-node create / close
# ------------------------------------------------------------------

class TestMode2Subnode(unittest.TestCase):
    def test_create_subnode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            owner = _TestOp.owner_id("ch1", "narrative/test/_node.md")
            storage = Storage(root, owner=owner)
            op = _TestOp(storage, narrative)

            child = op.create_subnode(narrative, "ch1")
            self.assertTrue(child.exists())
            parent_text = narrative.md_path().read_text()  # type: ignore[union-attr]
            self.assertIn("[testop:ch1]: #", parent_text)
            child_text = child.md_path().read_text()  # type: ignore[union-attr]
            self.assertIn("# ch1", child_text)

    def test_close_subnode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            owner = _TestOp.owner_id("ch1", "narrative/test/_node.md")
            storage = Storage(root, owner=owner)
            op = _TestOp(storage, narrative)

            op.create_subnode(narrative, "ch1")
            op.close_subnode(narrative, "ch1", "Summary of ch1.")
            parent_text = narrative.md_path().read_text()  # type: ignore[union-attr]
            self.assertIn("Summary of ch1.", parent_text)
            self.assertIn("[/testop:ch1]: #", parent_text)

    def test_create_subnode_promotes_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            leaf_path = root / "narrative" / "test" / "leaf.md"
            leaf_path.write_text("# leaf\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "add leaf"],
                cwd=root, capture_output=True, check=True,
            )

            leaf_node = NarrativeNode(
                narrative_root=narrative.narrative_root,
                key_path=("leaf",),
            )
            self.assertTrue(leaf_node.is_leaf())

            owner = _TestOp.owner_id("sub", "narrative/test/leaf/_node.md")
            storage = Storage(root, owner=owner)
            op = _TestOp(storage, leaf_node)
            child = op.create_subnode(leaf_node, "sub")
            self.assertFalse(leaf_node.is_leaf())
            self.assertTrue(child.exists())


# ------------------------------------------------------------------
# Mode 1: inline content
# ------------------------------------------------------------------

class TestMode1Inline(unittest.TestCase):
    def test_write_inline_single_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            owner = _TestOp.owner_id("w1", "narrative/test/_node.md")
            storage = Storage(root, owner=owner)
            op = _TestOp(storage, narrative)

            op.write_inline(narrative, "w1", "Generated text.")
            text = narrative.md_path().read_text()  # type: ignore[union-attr]
            self.assertIn("[testop:w1]: #", text)
            self.assertIn("Generated text.", text)
            self.assertIn("[/testop:w1]: #", text)

    def test_open_and_close_inline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            owner = _TestOp.owner_id("m1", "narrative/test/_node.md")
            storage = Storage(root, owner=owner)
            op = _TestOp(storage, narrative)

            op.open_inline(narrative, "m1", {"prompt": "go"})
            text = narrative.md_path().read_text()  # type: ignore[union-attr]
            self.assertIn("[testop:m1", text)
            self.assertIn("steps: 1", text)
            self.assertNotIn("[/testop:m1]", text)

            op.close_inline(narrative, "m1")
            text = narrative.md_path().read_text()  # type: ignore[union-attr]
            self.assertIn("[/testop:m1]: #", text)

    def test_continue_inline_increments_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            owner = _TestOp.owner_id("m1", "narrative/test/_node.md")
            storage = Storage(root, owner=owner)
            op = _TestOp(storage, narrative)

            op.open_inline(narrative, "m1")
            op.continue_inline(narrative, "m1", "More content.")
            text = narrative.md_path().read_text()  # type: ignore[union-attr]
            self.assertIn("steps: 2", text)
            self.assertIn("More content.", text)


# ------------------------------------------------------------------
# Mode 3: mutation (claim / propose / cancel)
# ------------------------------------------------------------------

class TestMode3Mutation(unittest.TestCase):
    def test_claim_propose_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            target = root / "narrative" / "test" / "_node.md"
            target.write_text("line1\nline2\nline3\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "content"],
                cwd=root, capture_output=True, check=True,
            )

            owner = _TestOp.owner_id("fix1", "narrative/test/_node.md")
            storage = Storage(root, owner=owner)
            op = _TestOp(storage, narrative)

            op.start_mutation(target, 2, 2, "fix1")
            self.assertFalse(storage.has_pending())
            text = target.read_text()
            self.assertIn("[testop:fix1]: #", text)
            self.assertIn("line2", text)
            self.assertIn("[/testop:fix1]: #", text)

            op.propose_mutation(target, "fix1", "REPLACED")
            text = target.read_text()
            self.assertNotIn("[testop:fix1]: #", text)
            self.assertIn("REPLACED", text)
            self.assertNotIn("line2", text)

    def test_cancel_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            target = root / "narrative" / "test" / "_node.md"
            target.write_text("line1\nline2\nline3\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "content"],
                cwd=root, capture_output=True, check=True,
            )

            owner = _TestOp.owner_id("fix1", "narrative/test/_node.md")
            storage = Storage(root, owner=owner)
            op = _TestOp(storage, narrative)

            op.start_mutation(target, 2, 2, "fix1")
            op.cancel_mutation(target, "fix1")
            text = target.read_text()
            self.assertNotIn("[testop:fix1]: #", text)
            self.assertNotIn("[/testop:fix1]: #", text)
            self.assertIn("line2", text)
            self.assertFalse(storage.has_pending())
