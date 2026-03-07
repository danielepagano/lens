"""Tests for the rollback command, covering both inline and mutation paths."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.address import NarrativeAddress
from lens.core.commands.rollback import compensating_rollback
from lens.core.narrative import NarrativeNode
from lens.core.operators.edit import EditOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage


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


class TestCompensatingRollback(unittest.TestCase):
    """compensating_rollback removes claim tags and restores original text."""

    def _stage_claim(
        self,
        root: Path,
        node: NarrativeNode,
        rel_path: str,
        ann_id: str,
        start_line: int,
        end_line: int,
        prompt: str = "fix it",
    ) -> None:
        owner = EditOperator.owner_id(ann_id, rel_path)
        op = EditOperator(Storage(root, owner=owner), node)
        op.start_mutation(node.md_path(), start_line, end_line, ann_id, {"prompt": prompt})

    def test_restores_original_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Line one.\nLine two.\nLine three.\n")

            rel_path = "narrative/test/_node.md"
            self._stage_claim(root, narrative, rel_path, "e2_2", 2, 2)

            # Simulate a proposal: write some replacement content (unstaged)
            node_file = narrative.md_path()
            op = EditOperator(Storage(root), narrative)
            op.propose_mutation(node_file, "e2_2", "PROPOSED")

            self.assertTrue(Storage(root).has_pending())

            owner = NarrativeAddress.from_file_and_annotation(
                rel_path, operator="edit", op_id="e2_2"
            )
            compensating_rollback(Storage(root), owner, root)

            result = node_file.read_text()
            self.assertIn("Line one.", result)
            self.assertIn("Line two.", result)
            self.assertIn("Line three.", result)
            self.assertNotIn("[edit:e2_2", result)
            self.assertNotIn("[/edit:e2_2", result)
            self.assertNotIn("PROPOSED", result)
            self.assertFalse(Storage(root).has_pending())

    def test_no_pending_after_compensating_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Alpha.\nBeta.\n")

            rel_path = "narrative/test/_node.md"
            self._stage_claim(root, narrative, rel_path, "e1_1", 1, 1)
            op = EditOperator(Storage(root), narrative)
            op.propose_mutation(narrative.md_path(), "e1_1", "NEW")

            owner = NarrativeAddress.from_file_and_annotation(
                rel_path, operator="edit", op_id="e1_1"
            )
            compensating_rollback(Storage(root), owner, root)

            self.assertFalse(Storage(root).has_pending())

    def test_is_mutation_detection(self) -> None:
        """Mutation owners have op_id set; inline owners do not."""
        mut_owner = NarrativeAddress.from_file_and_annotation(
            "narrative/test/_node.md", operator="edit", op_id="e1_1"
        )
        self.assertIsNotNone(mut_owner.op_id)

        inline_owner = NarrativeAddress.from_file_and_annotation(
            "narrative/test/_node.md", operator="write", op_id=None, line=5
        )
        self.assertIsNone(inline_owner.op_id)

    def test_check_rollback_status_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_content(root, narrative, "Line one.\nLine two.\nLine three.\n")
            
            # Start a mutation (edit)
            rel_path = "narrative/test/_node.md"
            self._stage_claim(root, narrative, rel_path, "e1", 2, 2)
            op = EditOperator(Storage(root), narrative)
            op.propose_mutation(narrative.md_path(), "e1", "PROPOSED")
            
            from lens.core.commands.rollback import check_rollback_status
            status = check_rollback_status(ProjectSession(root, root))
            self.assertTrue(status.has_pending)
            self.assertTrue(status.is_mutation)
            self.assertIsNotNone(status.owner)
            assert status.owner is not None
            self.assertEqual(status.owner.operator, "edit")

    def test_check_rollback_status_section_not_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            # Create a pending transaction for a section (not a mutation)
            # We can simulate this by instantiating SectionOperator and calling start()
            from lens.core.operators.section import SectionOperator
            owner = SectionOperator.owner_id("sec1", "narrative/test/_node.md")
            op = SectionOperator(Storage(root, owner=owner), narrative)
            op.start("sec1")

            from lens.core.commands.rollback import check_rollback_status
            status = check_rollback_status(ProjectSession(root, root))
            self.assertTrue(status.has_pending)
            self.assertFalse(status.is_mutation)
            self.assertIsNotNone(status.owner)
            assert status.owner is not None
            self.assertEqual(status.owner.operator, "section")
