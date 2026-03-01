"""Tests for the SectionOperator.section_range ("after the fact") feature."""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.llm import FinalPayload, StreamEvent
from lens.core.narrative import NarrativeNode
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


async def _fake_summary(*args: Any, **kwargs: Any) -> Any:
    for chunk in ["Section", " summary."]:
        yield StreamEvent(preview=chunk)
    yield StreamEvent(
        final=FinalPayload(
            text="Section summary.",
            tool_call=None,
            usage=None,
            interrupted=False,
        )
    )


def _run_section_range(
    root: Path,
    narrative: NarrativeNode,
    target_node: NarrativeNode,
    section_id: str,
    start_line: int,
    end_line: int,
    *,
    generate_mock: Any = None,
) -> None:
    mock = generate_mock or _fake_summary
    target_md = target_node.md_path()
    rel_path = str(target_md.relative_to(root))
    owner = SectionOperator.owner_id(section_id, rel_path)
    storage = Storage(root, owner=owner)
    op = SectionOperator(storage, narrative)

    with patch("lens.core.operators.section.generate_stream", new=mock):
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(
                op.section_range(
                    target_node=target_node,
                    id=section_id,
                    start_line=start_line,
                    end_line=end_line,
                    session=ProjectSession(root, root),
                    pins=[],
                    unpins=[],
                    llm_id=None,
                )
            )


# ---------------------------------------------------------------------------
# Happy-path: plain text selection (no sub-nodes)
# ---------------------------------------------------------------------------

class TestSectionRangePlainText(unittest.TestCase):

    def test_child_node_created_with_selected_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble line.\nSelected line one.\nSelected line two.\nTrailing line.\n"
            _commit_content(root, narrative, content)

            _run_section_range(root, narrative, narrative, "aside", 2, 3)

            child = narrative.child_node("aside")
            self.assertTrue(child.exists())
            child_text = child.md_path().read_text()
            self.assertIn("Selected line one.", child_text)
            self.assertIn("Selected line two.", child_text)

    def test_parent_contains_section_annotation_with_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble line.\nSelected line one.\nSelected line two.\nTrailing line.\n"
            _commit_content(root, narrative, content)

            _run_section_range(root, narrative, narrative, "aside", 2, 3)

            parent_text = narrative.md_path().read_text()
            self.assertIn("[section:aside]: #", parent_text)
            self.assertIn("[/section:aside]: #", parent_text)
            self.assertIn("Section summary.", parent_text)

    def test_parent_no_longer_contains_selected_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble line.\nSelected line one.\nSelected line two.\nTrailing line.\n"
            _commit_content(root, narrative, content)

            _run_section_range(root, narrative, narrative, "aside", 2, 3)

            parent_text = narrative.md_path().read_text()
            self.assertNotIn("Selected line one.", parent_text)
            self.assertNotIn("Selected line two.", parent_text)

    def test_parent_retains_lines_outside_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = "Preamble line.\nSelected line one.\nSelected line two.\nTrailing line.\n"
            _commit_content(root, narrative, content)

            _run_section_range(root, narrative, narrative, "aside", 2, 3)

            parent_text = narrative.md_path().read_text()
            self.assertIn("Preamble line.", parent_text)
            self.assertIn("Trailing line.", parent_text)

    def test_operation_leaves_pending_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Alpha.\nBeta.\nGamma.\n")

            _run_section_range(root, narrative, narrative, "mid", 2, 2)

            self.assertTrue(Storage(root).has_pending())

    def test_leaf_parent_promoted_to_folder(self) -> None:
        """A leaf root node (unlikely but possible for child nodes) gets promoted."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            # Create a leaf child node to use as the target
            child_dir = narrative.md_path().parent / "scene"
            child_dir.mkdir()
            child_md = child_dir / "_node.md"
            child_md.write_text("Opening.\nAction.\nConclusion.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "scene"], cwd=root, capture_output=True, check=True)

            # Convert to a leaf so we can test promotion
            scene_leaf = narrative.md_path().parent / "scene.md"
            scene_leaf.write_text("Opening.\nAction.\nConclusion.\n")
            child_dir_md = child_dir / "_node.md"
            if child_dir_md.exists():
                child_dir_md.unlink()
            if child_dir.exists() and not any(child_dir.iterdir()):
                child_dir.rmdir()

            # Re-create as a proper leaf
            scene_leaf.write_text("Opening.\nAction.\nConclusion.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "leaf"], cwd=root, capture_output=True, check=True)

            scene_node = NarrativeNode(
                narrative_root=narrative.narrative_root,
                key_path=("scene",),
            )
            self.assertTrue(scene_node.is_leaf())

            _run_section_range(root, narrative, scene_node, "action", 2, 2)

            # scene should now be a folder node
            self.assertFalse(scene_node.is_leaf())
            self.assertTrue(scene_node.child_node("action").exists())


# ---------------------------------------------------------------------------
# Happy-path: selection containing a fully-enclosed annotation + sub-node
# ---------------------------------------------------------------------------

class TestSectionRangeWithSubnodes(unittest.TestCase):

    def _setup_with_child(
        self, root: Path, narrative: NarrativeNode
    ) -> tuple[NarrativeNode, str]:
        """Set up a node with a closed section annotation and a matching child node."""
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

            # The section annotation spans lines 3–7 (open, blank, summary, blank, close)
            # We select lines 1–9 to wrap everything in a new section.
            _run_section_range(root, narrative, narrative, "chapter", 1, 9)

            chapter = narrative.child_node("chapter")
            self.assertTrue(chapter.exists())

            # The quest sub-node should now live inside chapter/
            quest_inside_chapter = chapter.child_node("quest")
            self.assertTrue(quest_inside_chapter.exists())

    def test_original_subnode_location_gone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            self._setup_with_child(root, narrative)

            _run_section_range(root, narrative, narrative, "chapter", 1, 9)

            parent_dir = narrative.md_path().parent
            old_quest_dir = parent_dir / "quest"
            # The original location should be gone (moved inside chapter/).
            self.assertFalse(old_quest_dir.exists())

    def test_child_content_preserved_in_moved_subnode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            self._setup_with_child(root, narrative)

            _run_section_range(root, narrative, narrative, "chapter", 1, 9)

            chapter = narrative.child_node("chapter")
            quest_inside = chapter.child_node("quest")
            self.assertIn("Quest detail content.", quest_inside.md_path().read_text())

    def test_section_annotation_preserved_in_child_node(self) -> None:
        """The extracted content (including its own annotations) lands in the child node."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            self._setup_with_child(root, narrative)

            _run_section_range(root, narrative, narrative, "chapter", 1, 9)

            chapter = narrative.child_node("chapter")
            child_text = chapter.md_path().read_text()
            self.assertIn("[section:quest]: #", child_text)
            self.assertIn("[/section:quest]: #", child_text)

    def test_leaf_subnode_moved_correctly(self) -> None:
        """A leaf child .md file is moved, not just a folder."""
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

            _run_section_range(root, narrative, narrative, "wrapper", 1, 5)

            wrapper = narrative.child_node("wrapper")
            self.assertTrue(wrapper.exists())
            leaf_inside = wrapper.child_node("leaf_child")
            self.assertTrue(leaf_inside.exists())
            self.assertIn("Leaf detail.", leaf_inside.md_path().read_text())
            self.assertFalse((parent_dir / "leaf_child.md").exists())


# ---------------------------------------------------------------------------
# Happy-path: selection that only partially overlaps child annotations
# (the annotation is fully inside — this is valid)
# ---------------------------------------------------------------------------

class TestSectionRangeAnnotationFullyInside(unittest.TestCase):

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

            # Lines 2–4 contain the self-closing annotation — fully inside.
            _run_section_range(root, narrative, narrative, "chunk", 2, 4)

            parent_text = narrative.md_path().read_text()
            self.assertIn("[section:chunk]: #", parent_text)
            child_text = narrative.child_node("chunk").md_path().read_text()
            self.assertIn("[chat:aside/]: #", child_text)


# ---------------------------------------------------------------------------
# Validation: line range errors
# ---------------------------------------------------------------------------

class TestSectionRangeValidation(unittest.TestCase):

    def test_out_of_bounds_start_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Only one line.\n")

            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 0, 1)

    def test_out_of_bounds_end_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Only one line.\n")

            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 1, 99)

    def test_start_greater_than_end_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Line one.\nLine two.\n")

            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 3, 1)

    def test_duplicate_section_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            parent_dir = narrative.md_path().parent
            content = "Line one.\nLine two.\n"
            narrative.md_path().write_text(content)
            # Create a pre-existing child node with the same id.
            existing = parent_dir / "aside.md"
            existing.write_text("Existing.\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "dup"], cwd=root, capture_output=True, check=True)

            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "aside", 1, 2)

    # --- Annotation splitting ---

    def test_split_open_tag_raises(self) -> None:
        """Selection starts inside an annotation block (after its open tag)."""
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

            # start_line=2 is inside the multi-line open tag (lines 1–3)
            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 2, 7)

    def test_split_close_tag_not_included_raises(self) -> None:
        """Selection ends before the close tag of a block that started inside."""
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

            # Selection covers the open tag (line 3) but cuts off before close (line 7)
            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 3, 5)

    def test_open_tag_before_range_body_inside_raises(self) -> None:
        """Open tag is before the range but body content is inside — must error."""
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

            # Range starts at line 2 (inside body), open tag is at line 1
            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 2, 5)

    def test_close_tag_after_range_raises(self) -> None:
        """Block starts inside range but close tag is after range end — must error."""
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

            # Range ends at line 6 — the close tag is on line 7
            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 3, 6)

    def test_unclosed_annotation_in_range_raises(self) -> None:
        """An unclosed cursor annotation that overlaps the range is rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "Preamble.\n"
                "\n"
                "[section:active]: #\n"
            )
            _commit_content(root, narrative, content)

            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 1, 3)

    def test_front_matter_split_raises(self) -> None:
        """A selection that cuts through the front matter block is rejected."""
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

            # Lines 2–4 are inside the front matter; line 1 is the opening bracket
            with self.assertRaises(ValueError):
                _run_section_range(root, narrative, narrative, "bad", 2, 6)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

class TestSectionRangeRollback(unittest.TestCase):

    def test_rollback_restores_parent_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            original = "First line.\nSecond line.\nThird line.\n"
            _commit_content(root, narrative, original)

            _run_section_range(root, narrative, narrative, "mid", 2, 2)
            self.assertTrue(Storage(root).has_pending())

            Storage(root).rollback()

            restored = narrative.md_path().read_text()
            self.assertEqual(restored, original)
            self.assertFalse(Storage(root).has_pending())

    def test_rollback_removes_child_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Alpha.\nBeta.\nGamma.\n")

            _run_section_range(root, narrative, narrative, "beta_section", 2, 2)

            Storage(root).rollback()

            self.assertFalse(narrative.child_node("beta_section").exists())

    def test_rollback_restores_moved_subnode(self) -> None:
        """A sub-node moved into the new section is restored to its original location."""
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

            _run_section_range(root, narrative, narrative, "chapter", 1, 5)

            # quest is now inside chapter/
            chapter = narrative.child_node("chapter")
            self.assertTrue(chapter.child_node("quest").exists())

            Storage(root).rollback()

            # quest should be back at the root level
            self.assertTrue(narrative.child_node("quest").exists())
            self.assertFalse((parent_dir / "chapter").exists())


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestSectionRangeEdgeCases(unittest.TestCase):

    def test_empty_llm_response_raises(self) -> None:
        async def _empty(*args: Any, **kwargs: Any) -> Any:
            yield StreamEvent(
                final=FinalPayload(
                    text="",
                    tool_call=None,
                    usage=None,
                    interrupted=False,
                )
            )

        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Some content.\n")

            with self.assertRaises(ValueError):
                _run_section_range(
                    root, narrative, narrative, "empty", 1, 1,
                    generate_mock=_empty,
                )

    def test_selection_covering_entire_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Line one.\nLine two.\n")

            _run_section_range(root, narrative, narrative, "all", 1, 2)

            parent_text = narrative.md_path().read_text()
            self.assertIn("[section:all]: #", parent_text)
            child_text = narrative.child_node("all").md_path().read_text()
            self.assertIn("Line one.", child_text)
            self.assertIn("Line two.", child_text)

    def test_annotation_fully_before_range_is_not_moved(self) -> None:
        """A sub-node whose annotation is entirely before the selection stays put."""
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

            # Section only line 7 (the plain line), not the early section block.
            _run_section_range(root, narrative, narrative, "later", 7, 7)

            # early/ should remain at the root level — it was outside the range.
            self.assertTrue((parent_dir / "early").is_dir())
            self.assertTrue(narrative.child_node("early").exists())

    def test_annotation_fully_after_range_is_not_moved(self) -> None:
        """A sub-node whose annotation is entirely after the selection stays put."""
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

            _run_section_range(root, narrative, narrative, "early", 1, 1)

            self.assertTrue((parent_dir / "late").is_dir())
            self.assertTrue(narrative.child_node("late").exists())

    def test_unclosed_annotation_outside_range_does_not_error(self) -> None:
        """An unclosed cursor annotation that is entirely after the range is fine."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            content = (
                "Sectionable text.\n"
                "\n"
                "[section:open_cursor]: #\n"
            )
            _commit_content(root, narrative, content)

            # The unclosed annotation is at line 3; we section only line 1.
            _run_section_range(root, narrative, narrative, "chunk", 1, 1)

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

            _run_section_range(root, narrative, narrative, "combined", 1, 12)

            combined = narrative.child_node("combined")
            self.assertTrue(combined.exists())
            self.assertTrue(combined.child_node("alpha").exists())
            self.assertTrue(combined.child_node("beta").exists())
            self.assertFalse((parent_dir / "alpha").exists())
            self.assertFalse((parent_dir / "beta").exists())
