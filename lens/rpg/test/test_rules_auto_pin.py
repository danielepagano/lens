"""Tests for play operator rules auto-pin (``_inject_rules_companions``)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from lens.core.context import CrawlResult
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.rpg.operators.play import PlayOperator


def _init_repo(tmp: Path) -> None:
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


def _make_project(tmp: Path, *, rules_types: list[str] | None = None) -> Path:
    """Create a minimal project with optional ``rules.<type>`` KB objects."""
    (tmp / "lens.toml").write_text(
        '[project]\nnarrative = "test"\ndatasets = ["rpg"]\n'
        '[[llm]]\nbase_url = "https://api.example.com/v1"\nmodel = "test"\n'
    )
    (tmp / "narrative" / "test").mkdir(parents=True)
    (tmp / "narrative" / "test" / "_node.md").write_text("# test\n")
    (tmp / "knowledge").mkdir(exist_ok=True)

    for rtype in rules_types or []:
        rules_dir = tmp / "knowledge" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / f"{rtype}.md").write_text(f"Rules for {rtype}\n")

    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def _make_operator(project_root: Path) -> PlayOperator:
    """Create a PlayOperator with a mock storage pointing at *project_root*."""
    narrative_root = project_root / "narrative" / "test"
    narrative = NarrativeNode(narrative_root=narrative_root, key_path=())
    storage = MagicMock()
    storage.git_root = project_root
    op = PlayOperator(storage, narrative)
    return op


class TestInjectRulesCompanions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        KnowledgeStore.clear_registry()

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        self._tmp.cleanup()

    def test_injects_rules_for_pinned_encounter(self) -> None:
        """When encounter.foo is pinned and rules.encounter exists, inject it."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=["encounter"])
        op = _make_operator(tmp)

        cr = CrawlResult(
            knowledge=["existing KB"],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["rules.system", "rules.rpg", "pc.alice", "encounter.bridge"],
            project_root=tmp,
        )
        op._inject_rules_companions(cr)  # pyright: ignore[reportPrivateUsage]

        self.assertIn("rules.encounter", cr.pinned_ids)
        self.assertTrue(
            any("Rules for encounter" in k for k in cr.knowledge),
            f"rules.encounter content not found in knowledge: {cr.knowledge}",
        )

    def test_no_injection_when_rules_missing(self) -> None:
        """When encounter.foo is pinned but rules.encounter doesn't exist, skip."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=[])  # no rules.encounter
        op = _make_operator(tmp)

        cr = CrawlResult(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["rules.system", "rules.rpg", "pc.alice", "encounter.bridge"],
            project_root=tmp,
        )
        op._inject_rules_companions(cr)  # pyright: ignore[reportPrivateUsage]

        self.assertNotIn("rules.encounter", cr.pinned_ids)
        self.assertEqual(cr.knowledge, [])

    def test_no_duplicate_when_already_pinned(self) -> None:
        """When rules.encounter is already pinned, don't add it again."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=["encounter"])
        op = _make_operator(tmp)

        cr = CrawlResult(
            knowledge=["already here"],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["rules.system", "rules.rpg", "rules.encounter", "encounter.bridge"],
            project_root=tmp,
        )
        op._inject_rules_companions(cr)  # pyright: ignore[reportPrivateUsage]

        # Should still be exactly one occurrence
        count = cr.pinned_ids.count("rules.encounter")
        self.assertEqual(count, 1)
        self.assertEqual(len(cr.knowledge), 1)  # unchanged

    def test_multiple_types(self) -> None:
        """Multiple pinned types each get their rules companion if it exists."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=["encounter", "front"])
        op = _make_operator(tmp)

        cr = CrawlResult(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["rules.system", "rules.rpg", "pc.alice", "encounter.bridge", "front.doom"],
            project_root=tmp,
        )
        op._inject_rules_companions(cr)  # pyright: ignore[reportPrivateUsage]

        self.assertIn("rules.encounter", cr.pinned_ids)
        self.assertIn("rules.front", cr.pinned_ids)
        self.assertEqual(len(cr.knowledge), 2)

    def test_rules_objects_dont_trigger_recursion(self) -> None:
        """Pinned rules.* objects don't trigger lookup for rules.rules."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=[])
        op = _make_operator(tmp)

        cr = CrawlResult(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["rules.system", "rules.rpg", "pc.alice"],
            project_root=tmp,
        )
        op._inject_rules_companions(cr)  # pyright: ignore[reportPrivateUsage]

        # pc type has no rules.pc, rules type is skipped
        self.assertEqual(len(cr.knowledge), 0)
        self.assertEqual(len(cr.pinned_ids), 3)  # unchanged

    def test_no_project_root_is_noop(self) -> None:
        """When project_root is None, injection is a no-op."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=["encounter"])
        op = _make_operator(tmp)

        cr = CrawlResult(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["encounter.bridge"],
            project_root=None,
        )
        op._inject_rules_companions(cr)  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(len(cr.knowledge), 0)
        self.assertEqual(len(cr.pinned_ids), 1)


if __name__ == "__main__":
    unittest.main()
