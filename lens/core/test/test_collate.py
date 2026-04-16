"""Tests for the CollateOperator (after-the-fact sectioning at an arbitrary address)."""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.collate import CollateOperator
from lens.core.operators.section import SectionOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage


# ---------------------------------------------------------------------------
# Repo / project helpers (identical pattern used across operator test files)
# ---------------------------------------------------------------------------

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
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def _make_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


def _commit_content(root: Path, node: NarrativeNode, content: str) -> None:
    node.md_path().write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "content"], cwd=root, capture_output=True, check=True,
    )


async def _fake_summary_text(*args: Any, **kwargs: Any) -> str:
    if kwargs.get("operator_name") == "remember":
        return ""
    on_preview = kwargs.get("on_preview")
    if on_preview is not None:
        cb = cast(Callable[[str], Awaitable[None]], on_preview)
        await cb("Section")
        await cb(" summary.")
    return "Section summary."


def _run_collate(
    root: Path,
    narrative: NarrativeNode,
    target_node: NarrativeNode,
    section_id: str,
    start_line: int,
    end_line: int,
    *,
    generate_mock: Any = None,
) -> None:
    mock = generate_mock or _fake_summary_text
    address_str = (
        "/".join([target_node.narrative_root.name] + list(target_node.key_path))
        if target_node.key_path
        else target_node.narrative_root.name
    )

    with patch("lens.core.operators.session.generate_text", new=mock):
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(
                CollateOperator.run_collate(
                    session=ProjectSession(root, root),
                    narrative=narrative,
                    id=section_id,
                    address_str=address_str,
                    start_line=start_line,
                    end_line=end_line,
                    pins=[],
                    unpins=[],
                    llm_id=None,
                )
            )


# ---------------------------------------------------------------------------
# Happy-path: plain text selection (no sub-nodes)
# ---------------------------------------------------------------------------

class TestCollatePlainText(unittest.TestCase):

    def test_child_node_created_with_selected_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble line.\nSelected line one.\nSelected line two.\nTrailing line.\n"
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "aside", 2, 3)

            child = narrative.child_node("aside")
            self.assertTrue(child.exists())
            child_text = child.md_path().read_text()
            self.assertIn("Selected line one.", child_text)
            self.assertIn("Selected line two.", child_text)

    def test_creates_leaf_node_when_no_sections_under_range(self) -> None:
        """Collating a plain range (no sub-sections) creates a leaf file, not a folder."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble.\nSelected content.\nTrailing.\n"
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "aside", 2, 2)

            child = narrative.child_node("aside")
            self.assertTrue(child.exists())
            self.assertTrue(
                child.is_leaf(),
                "child should be a leaf when range has no sections",
            )
            self.assertEqual(
                child.md_path(),
                narrative.md_path().parent / "aside.md",
            )
            self.assertFalse(
                (narrative.md_path().parent / "aside" / "_node.md").exists(),
            )

    def test_parent_contains_section_annotation_with_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble line.\nSelected line one.\nSelected line two.\nTrailing line.\n"
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "aside", 2, 3)

            parent_text = narrative.md_path().read_text()
            self.assertIn("[section:aside]: #", parent_text)
            self.assertIn("[/section:aside]: #", parent_text)
            self.assertIn("Section summary.", parent_text)

    def test_parent_no_longer_contains_selected_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble line.\nSelected line one.\nSelected line two.\nTrailing line.\n"
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "aside", 2, 3)

            parent_text = narrative.md_path().read_text()
            self.assertNotIn("Selected line one.", parent_text)
            self.assertNotIn("Selected line two.", parent_text)

    def test_parent_retains_lines_outside_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble line.\nSelected line one.\nSelected line two.\nTrailing line.\n"
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "aside", 2, 3)

            parent_text = narrative.md_path().read_text()
            self.assertIn("Preamble line.", parent_text)
            self.assertIn("Trailing line.", parent_text)

    def test_operation_leaves_pending_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Alpha.\nBeta.\nGamma.\n")

            _run_collate(root, narrative, narrative, "mid", 2, 2)

            self.assertTrue(Storage(root).has_pending())

    def test_leaf_parent_promoted_to_folder(self) -> None:
        """A leaf root node (unlikely but possible for child nodes) gets promoted."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            child_dir = narrative.md_path().parent / "scene"
            child_dir.mkdir()
            child_md = child_dir / "_node.md"
            child_md.write_text("Opening.\nAction.\nConclusion.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "scene"], cwd=root, capture_output=True, check=True)

            scene_leaf = narrative.md_path().parent / "scene.md"
            scene_leaf.write_text("Opening.\nAction.\nConclusion.\n")
            child_dir_md = child_dir / "_node.md"
            if child_dir_md.exists():
                child_dir_md.unlink()
            if child_dir.exists() and not any(child_dir.iterdir()):
                child_dir.rmdir()

            scene_leaf.write_text("Opening.\nAction.\nConclusion.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "leaf"], cwd=root, capture_output=True, check=True)

            scene_node = NarrativeNode(
                narrative_root=narrative.narrative_root,
                key_path=("scene",),
            )
            self.assertTrue(scene_node.is_leaf())

            _run_collate(root, narrative, scene_node, "action", 2, 2)

            self.assertFalse(scene_node.is_leaf())
            self.assertTrue(scene_node.child_node("action").exists())


# ---------------------------------------------------------------------------
# Happy-path: selection containing a fully-enclosed annotation + sub-node
# ---------------------------------------------------------------------------

class TestCollateWithSubnodes(unittest.TestCase):

    def _setup_with_child(
        self, root: Path, narrative: NarrativeNode
    ) -> tuple[NarrativeNode, str]:
        parent_dir = narrative.md_path().parent
        content = (
            "Intro text.\n"
            "\n"
            "[section:quest]: #\n"
            "\n"
            "The quest summary.\n"
            "\n"
            "[/section:quest]: #\n"
            "\n"
            "Outro text.\n"
        )
        narrative.md_path().write_text(content)
        quest_dir = parent_dir / "quest"
        quest_dir.mkdir()
        (quest_dir / "_node.md").write_text("Quest detail content.\n")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "with-child"], cwd=root, capture_output=True, check=True)
        return narrative, content

    def test_subnode_moved_into_new_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            self._setup_with_child(root, narrative)

            _run_collate(root, narrative, narrative, "chapter", 1, 9)

            chapter = narrative.child_node("chapter")
            self.assertTrue(chapter.exists())
            self.assertFalse(
                chapter.is_leaf(),
                "child should be a folder when range contains sub-sections",
            )

            quest_inside_chapter = chapter.child_node("quest")
            self.assertTrue(quest_inside_chapter.exists())

    def test_original_subnode_location_gone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            self._setup_with_child(root, narrative)

            _run_collate(root, narrative, narrative, "chapter", 1, 9)

            parent_dir = narrative.md_path().parent
            old_quest_dir = parent_dir / "quest"
            self.assertFalse(old_quest_dir.exists())

    def test_child_content_preserved_in_moved_subnode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            self._setup_with_child(root, narrative)

            _run_collate(root, narrative, narrative, "chapter", 1, 9)

            chapter = narrative.child_node("chapter")
            quest_inside = chapter.child_node("quest")
            self.assertIn("Quest detail content.", quest_inside.md_path().read_text())

    def test_section_annotation_preserved_in_child_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            self._setup_with_child(root, narrative)

            _run_collate(root, narrative, narrative, "chapter", 1, 9)

            chapter = narrative.child_node("chapter")
            child_text = chapter.md_path().read_text()
            self.assertIn("[section:quest]: #", child_text)
            self.assertIn("[/section:quest]: #", child_text)

    def test_leaf_subnode_moved_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            parent_dir = narrative.md_path().parent
            content = (
                "[section:leaf_child]: #\n"
                "\n"
                "Leaf summary.\n"
                "\n"
                "[/section:leaf_child]: #\n"
            )
            narrative.md_path().write_text(content)
            (parent_dir / "leaf_child.md").write_text("Leaf detail.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "leaf-child"], cwd=root, capture_output=True, check=True)

            _run_collate(root, narrative, narrative, "wrapper", 1, 5)

            wrapper = narrative.child_node("wrapper")
            self.assertTrue(wrapper.exists())
            leaf_inside = wrapper.child_node("leaf_child")
            self.assertTrue(leaf_inside.exists())
            self.assertIn("Leaf detail.", leaf_inside.md_path().read_text())
            self.assertFalse((parent_dir / "leaf_child.md").exists())


# ---------------------------------------------------------------------------
# Happy-path: selection that only partially overlaps child annotations
# ---------------------------------------------------------------------------

class TestCollateAnnotationFullyInside(unittest.TestCase):

    def test_fully_contained_self_closing_annotation_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "Before.\n"
                "\n"
                "[chat:aside/]: #\n"
                "\n"
                "After.\n"
            )
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "chunk", 2, 4)

            parent_text = narrative.md_path().read_text()
            self.assertIn("[section:chunk]: #", parent_text)
            child_text = narrative.child_node("chunk").md_path().read_text()
            self.assertIn("[chat:aside/]: #", child_text)


# ---------------------------------------------------------------------------
# Validation: line range errors
# ---------------------------------------------------------------------------

class TestCollateValidation(unittest.TestCase):

    def test_out_of_bounds_start_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Only one line.\n")

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "bad", 0, 1)

    def test_out_of_bounds_end_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Only one line.\n")

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "bad", 1, 99)

    def test_start_greater_than_end_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Line one.\nLine two.\n")

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "bad", 3, 1)

    def test_duplicate_section_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            parent_dir = narrative.md_path().parent
            content = "Line one.\nLine two.\n"
            narrative.md_path().write_text(content)
            existing = parent_dir / "aside.md"
            existing.write_text("Existing.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "dup"], cwd=root, capture_output=True, check=True)

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "aside", 1, 2)

    def test_split_write_block_strips_fences_from_parent_and_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "[write\n"
                "  prompt: hello\n"
                "]: #\n"
                "\n"
                "Content here.\n"
                "\n"
                "[/write]: #\n"
            )
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "chunk", 2, 7)

            parent_text = narrative.md_path().read_text()
            self.assertNotIn("[write", parent_text)
            self.assertNotIn("[/write]", parent_text)
            child_text = narrative.child_node("chunk").md_path().read_text()
            self.assertIn("Content here.", child_text)
            self.assertNotIn("[write", child_text)
            self.assertNotIn("[/write]", child_text)
            self.assertNotIn("prompt: hello", child_text)

    def test_split_write_body_only_strips_opener_and_closer_from_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "[write\n"
                "  prompt: hello\n"
                "]: #\n"
                "\n"
                "Keep before.\n"
                "Take this line.\n"
                "Keep after.\n"
                "\n"
                "[/write]: #\n"
            )
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "mid", 6, 6)

            parent_text = narrative.md_path().read_text()
            self.assertNotIn("[write", parent_text)
            self.assertNotIn("[/write]", parent_text)
            self.assertIn("Keep before.", parent_text)
            self.assertIn("Keep after.", parent_text)
            self.assertNotIn("Take this line.", parent_text)
            child_text = narrative.child_node("mid").md_path().read_text()
            self.assertIn("Take this line.", child_text)
            self.assertNotIn("[write", child_text)

    def test_split_close_tag_not_included_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "Preamble.\n"
                "\n"
                "[section:inner]: #\n"
                "\n"
                "Inner content.\n"
                "\n"
                "[/section:inner]: #\n"
                "\n"
                "Epilogue.\n"
            )
            _commit_content(root, narrative, content)

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "bad", 3, 5)

    def test_open_tag_before_range_body_inside_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "[section:inner]: #\n"
                "\n"
                "Inner body.\n"
                "\n"
                "[/section:inner]: #\n"
            )
            _commit_content(root, narrative, content)

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "bad", 2, 5)

    def test_close_tag_after_range_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "Preamble.\n"
                "\n"
                "[section:inner]: #\n"
                "\n"
                "Inner body.\n"
                "\n"
                "[/section:inner]: #\n"
                "\n"
                "Epilogue.\n"
            )
            _commit_content(root, narrative, content)

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "bad", 3, 6)

    def test_unclosed_annotation_in_range_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "Preamble.\n"
                "\n"
                "[section:active]: #\n"
            )
            _commit_content(root, narrative, content)

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "bad", 1, 3)

    def test_front_matter_split_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "[\n"
                "  kb_pin:\n"
                "    - place.city\n"
                "]: #\n"
                "\n"
                "Narrative text.\n"
            )
            _commit_content(root, narrative, content)

            with self.assertRaises(ValueError):
                _run_collate(root, narrative, narrative, "bad", 2, 6)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

class TestCollateRollback(unittest.TestCase):

    def test_rollback_restores_parent_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            original = "First line.\nSecond line.\nThird line.\n"
            _commit_content(root, narrative, original)

            _run_collate(root, narrative, narrative, "mid", 2, 2)
            self.assertTrue(Storage(root).has_pending())

            Storage(root).rollback()

            restored = narrative.md_path().read_text()
            self.assertEqual(restored, original)
            self.assertFalse(Storage(root).has_pending())

    def test_rollback_removes_child_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Alpha.\nBeta.\nGamma.\n")

            _run_collate(root, narrative, narrative, "beta_section", 2, 2)

            Storage(root).rollback()

            self.assertFalse(narrative.child_node("beta_section").exists())

    def test_rollback_restores_moved_subnode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            parent_dir = narrative.md_path().parent
            content = (
                "[section:quest]: #\n"
                "\n"
                "Quest summary.\n"
                "\n"
                "[/section:quest]: #\n"
            )
            narrative.md_path().write_text(content)
            quest_dir = parent_dir / "quest"
            quest_dir.mkdir()
            (quest_dir / "_node.md").write_text("Quest content.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "quest"], cwd=root, capture_output=True, check=True)

            _run_collate(root, narrative, narrative, "chapter", 1, 5)

            chapter = narrative.child_node("chapter")
            self.assertTrue(chapter.child_node("quest").exists())

            Storage(root).rollback()

            self.assertTrue(narrative.child_node("quest").exists())
            self.assertFalse((parent_dir / "chapter").exists())


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestCollateEdgeCases(unittest.TestCase):

    def test_empty_llm_response_raises(self) -> None:
        async def _empty(*args: Any, **kwargs: Any) -> str:
            return ""

        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Some content.\n")

            with self.assertRaises(OperatorError):
                _run_collate(
                    root, narrative, narrative, "empty", 1, 1,
                    generate_mock=_empty,
                )

    def test_selection_covering_entire_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Line one.\nLine two.\n")

            _run_collate(root, narrative, narrative, "all", 1, 2)

            parent_text = narrative.md_path().read_text()
            self.assertIn("[section:all]: #", parent_text)
            child_text = narrative.child_node("all").md_path().read_text()
            self.assertIn("Line one.", child_text)
            self.assertIn("Line two.", child_text)

    def test_annotation_fully_before_range_is_not_moved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            parent_dir = narrative.md_path().parent
            content = (
                "[section:early]: #\n"
                "\n"
                "Early summary.\n"
                "\n"
                "[/section:early]: #\n"
                "\n"
                "Plain line to section.\n"
            )
            narrative.md_path().write_text(content)
            early_dir = parent_dir / "early"
            early_dir.mkdir()
            (early_dir / "_node.md").write_text("Early content.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "early"], cwd=root, capture_output=True, check=True)

            _run_collate(root, narrative, narrative, "later", 7, 7)

            self.assertTrue((parent_dir / "early").is_dir())
            self.assertTrue(narrative.child_node("early").exists())

    def test_annotation_fully_after_range_is_not_moved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            parent_dir = narrative.md_path().parent
            content = (
                "Plain line to section.\n"
                "\n"
                "[section:late]: #\n"
                "\n"
                "Late summary.\n"
                "\n"
                "[/section:late]: #\n"
            )
            narrative.md_path().write_text(content)
            late_dir = parent_dir / "late"
            late_dir.mkdir()
            (late_dir / "_node.md").write_text("Late content.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "late"], cwd=root, capture_output=True, check=True)

            _run_collate(root, narrative, narrative, "early", 1, 1)

            self.assertTrue((parent_dir / "late").is_dir())
            self.assertTrue(narrative.child_node("late").exists())

    def test_unclosed_annotation_outside_range_does_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "Sectionable text.\n"
                "\n"
                "[section:open_cursor]: #\n"
            )
            _commit_content(root, narrative, content)

            _run_collate(root, narrative, narrative, "chunk", 1, 1)

            self.assertIn("[section:chunk]: #", narrative.md_path().read_text())

    def test_multiple_subnodes_in_range_all_moved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            parent_dir = narrative.md_path().parent
            content = (
                "[section:alpha]: #\n"
                "\n"
                "Alpha summary.\n"
                "\n"
                "[/section:alpha]: #\n"
                "\n"
                "[section:beta]: #\n"
                "\n"
                "Beta summary.\n"
                "\n"
                "[/section:beta]: #\n"
            )
            narrative.md_path().write_text(content)
            for name in ("alpha", "beta"):
                d = parent_dir / name
                d.mkdir()
                (d / "_node.md").write_text(f"{name} content.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "multi"], cwd=root, capture_output=True, check=True)

            _run_collate(root, narrative, narrative, "combined", 1, 12)

            combined = narrative.child_node("combined")
            self.assertTrue(combined.exists())
            self.assertTrue(combined.child_node("alpha").exists())
            self.assertTrue(combined.child_node("beta").exists())
            self.assertFalse((parent_dir / "alpha").exists())
            self.assertFalse((parent_dir / "beta").exists())


class TestCollateTransactionSemantics(unittest.TestCase):
    """Collate must leave one unstaged pending tx; returned Storage continues that owner."""

    def test_run_collate_returns_storage_unstaged_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "A.\nB.\nC.\n")
            with patch("lens.core.operators.session.generate_text", new=_fake_summary_text):
                with contextlib.redirect_stdout(io.StringIO()):
                    st = asyncio.run(
                        CollateOperator.run_collate(
                            session=ProjectSession(root, root),
                            narrative=narrative,
                            id="mid",
                            address_str=narrative.narrative_root.name,
                            start_line=2,
                            end_line=2,
                            pins=[],
                            unpins=[],
                            llm_id=None,
                        )
                    )
            self.assertIsInstance(st, Storage)
            self.assertTrue(st.has_pending())
            self.assertFalse(st.has_staged())
            rel = str(narrative.md_path().relative_to(root))
            self.assertEqual(
                st.detect_pending_owner(),
                SectionOperator.owner_id("mid", rel),
            )

    def test_follow_up_write_via_returned_storage_stays_unstaged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "A.\nB.\nC.\n")
            with patch("lens.core.operators.session.generate_text", new=_fake_summary_text):
                with contextlib.redirect_stdout(io.StringIO()):
                    st = asyncio.run(
                        CollateOperator.run_collate(
                            session=ProjectSession(root, root),
                            narrative=narrative,
                            id="mid",
                            address_str=narrative.narrative_root.name,
                            start_line=2,
                            end_line=2,
                            pins=[],
                            unpins=[],
                            llm_id=None,
                        )
                    )
            child_md = narrative.child_node("mid").md_path()
            existing = child_md.read_text(encoding="utf-8")
            st.write_file(child_md, existing.rstrip("\n") + "\n\npost-collate marker.\n")
            self.assertFalse(st.has_staged())
            self.assertTrue(st.has_pending())

    def test_new_system_storage_after_collate_stages_collate(self) -> None:
        """Regression: a fresh Storage(owner=None) auto-stages another owner's pending work."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "A.\nB.\nC.\n")
            session = ProjectSession(root, root)
            with patch("lens.core.operators.session.generate_text", new=_fake_summary_text):
                with contextlib.redirect_stdout(io.StringIO()):
                    asyncio.run(
                        CollateOperator.run_collate(
                            session=session,
                            narrative=narrative,
                            id="mid",
                            address_str=narrative.narrative_root.name,
                            start_line=2,
                            end_line=2,
                            pins=[],
                            unpins=[],
                            llm_id=None,
                        )
                    )
            self.assertTrue(Storage(root).has_pending())
            self.assertFalse(Storage(root).has_staged())
            sys_st = session.new_storage()
            sys_st.write_file(root / "_compress_sidecar.txt", "x\n")
            self.assertTrue(Storage(root).has_staged())


class TestCollateRememberAtChatChild(unittest.TestCase):
    def test_collate_remember_sees_child_pins_and_chat_as_with(self) -> None:
        """Collate on a chat session file merges chat extras into remember crawl."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            kb = root / "knowledge"
            (kb / "npc").mkdir(parents=True)
            (kb / "npc" / "bob.md").write_text("Bob.\n", encoding="utf-8")
            (kb / "pc").mkdir(parents=True)
            (kb / "pc" / "amy.md").write_text("Amy.\n", encoding="utf-8")
            (kb / "lore").mkdir(parents=True)
            (kb / "lore" / "alice.md").write_text("Alice.\n", encoding="utf-8")

            root_md = narrative.md_path()
            root_md.write_text(
                "# test\n\n"
                "[chat:chat-sess\n"
                "    as_kb_id: npc.bob\n"
                "    with_kb_id: pc.amy\n"
                "]: #\n",
                encoding="utf-8",
            )
            sess_dir = narrative.narrative_root / "chat-sess"
            sess_dir.mkdir()
            (sess_dir / "_node.md").write_text(
                "[\n"
                "  kb_pin:\n"
                "    - lore.alice\n"
                "]: #\n"
                "\n"
                "Alpha.\n"
                "Beta.\n"
                "Gamma.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "chat scene"],
                cwd=root,
                capture_output=True,
                check=True,
            )

            KnowledgeStore.clear_registry()
            store = KnowledgeStore.for_project(root)
            self.assertIsNone(store.add_tags("lore.alice", ["remember.note"]))

            chat_node = narrative.child_node("chat-sess")
            address_str = "/".join([narrative.narrative_root.name] + list(chat_node.key_path))

            captured: dict[str, list[str]] = {}

            async def _remember_cap(*, crawl_result: Any, **kw: Any) -> str:
                captured["pinned_ids"] = list(crawl_result.pinned_ids)
                return ""

            with patch("lens.core.operators.session.generate_text", new=_fake_summary_text):
                with patch(
                    "lens.core.operators.collate.apply_remember_patches",
                    AsyncMock(side_effect=_remember_cap),
                ):
                    with contextlib.redirect_stdout(io.StringIO()):
                        asyncio.run(
                            CollateOperator.run_collate(
                                session=ProjectSession(root, root),
                                narrative=narrative,
                                id="chunk",
                                address_str=address_str,
                                start_line=6,
                                end_line=7,
                                pins=[],
                                unpins=[],
                                llm_id=None,
                            )
                        )

            ids = captured["pinned_ids"]
            self.assertIn("lore.alice", ids)
            self.assertIn("npc.bob", ids)
            self.assertIn("pc.amy", ids)
