"""Tests for play rules companions (``rpg_play_context`` modality)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from lens.core.context import CrawlResult
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.modalities import (
    apply_modality_crawl,
    collect_modality_crawl_contribution,
    ensure_modalities_registered,
    resolve_modalities,
)
from lens.core.modalities.types import ModalityContext
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


def _apply_play_modalities(
    cr: CrawlResult, project_root: Path, narrative: NarrativeNode
) -> None:
    resolved, _ = resolve_modalities(PlayOperator, narrative)
    ctx = ModalityContext(
        session=None,
        narrative=narrative,
        focus_node=narrative,
        operator_name="play",
        crawl_result=cr,
        params={},
        project_root=project_root,
    )
    contrib = collect_modality_crawl_contribution(resolved, ctx)
    pinned = cr.graph.pinned_ids
    for pin in contrib.extra_pins:
        if pin not in pinned:
            pinned.append(pin)
    apply_modality_crawl(cr, resolved, ctx)


class TestInjectRulesCompanions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_modalities_registered()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self._tmp.cleanup()

    def test_injects_rules_for_pinned_encounter(self) -> None:
        """When encounter.foo is pinned and rules.encounter exists, inject it."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=["encounter"])
        narrative = NarrativeNode(
            narrative_root=tmp / "narrative" / "test", key_path=()
        )

        cr = CrawlResult.from_text_fields(
            knowledge=["existing KB"],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["pc.alice", "encounter.bridge"],
            project_root=tmp,
        )
        _apply_play_modalities(cr, tmp, narrative)

        pinned = cr.graph.pinned_ids
        self.assertIn("rules.system", pinned)
        self.assertIn("rules.rpg", pinned)
        self.assertIn("rules.encounter", pinned)
        self.assertTrue(
            any("Rules for encounter" in k for k in cr.knowledge),
            f"rules.encounter content not found in knowledge: {cr.knowledge}",
        )

    def test_no_injection_when_rules_missing(self) -> None:
        """When encounter.foo is pinned but rules.encounter doesn't exist, skip."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=[])
        narrative = NarrativeNode(
            narrative_root=tmp / "narrative" / "test", key_path=()
        )

        cr = CrawlResult.from_text_fields(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["pc.alice", "encounter.bridge"],
            project_root=tmp,
        )
        _apply_play_modalities(cr, tmp, narrative)

        self.assertNotIn("rules.encounter", cr.pinned_ids)

    def test_no_duplicate_when_already_pinned(self) -> None:
        """When rules.encounter is already pinned, don't add it again."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=["encounter"])
        narrative = NarrativeNode(
            narrative_root=tmp / "narrative" / "test", key_path=()
        )

        cr = CrawlResult.from_text_fields(
            knowledge=["already here"],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["rules.system", "rules.rpg", "rules.encounter", "encounter.bridge"],
            project_root=tmp,
        )
        _apply_play_modalities(cr, tmp, narrative)

        count = cr.pinned_ids.count("rules.encounter")
        self.assertEqual(count, 1)
        self.assertEqual(len(cr.knowledge), 1)

    def test_multiple_types(self) -> None:
        """Multiple pinned types each get their rules companion if it exists."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=["encounter", "front"])
        narrative = NarrativeNode(
            narrative_root=tmp / "narrative" / "test", key_path=()
        )

        cr = CrawlResult.from_text_fields(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["pc.alice", "encounter.bridge", "front.doom"],
            project_root=tmp,
        )
        _apply_play_modalities(cr, tmp, narrative)

        self.assertIn("rules.encounter", cr.pinned_ids)
        self.assertIn("rules.front", cr.pinned_ids)
        self.assertEqual(len(cr.knowledge), 2)

    def test_rules_objects_dont_trigger_recursion(self) -> None:
        """Pinned rules.* objects don't trigger lookup for rules.rules."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=[])
        narrative = NarrativeNode(
            narrative_root=tmp / "narrative" / "test", key_path=()
        )

        cr = CrawlResult.from_text_fields(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["pc.alice"],
            project_root=tmp,
        )
        _apply_play_modalities(cr, tmp, narrative)

        self.assertEqual(len(cr.knowledge), 0)
        self.assertIn("rules.system", cr.pinned_ids)

    def test_modality_auto_pins_use_context_project_root(self) -> None:
        """Auto-pins apply even when ``CrawlResult.project_root`` is unset."""
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        _make_project(tmp, rules_types=["encounter"])
        narrative = NarrativeNode(
            narrative_root=tmp / "narrative" / "test", key_path=()
        )

        cr = CrawlResult.from_text_fields(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["encounter.bridge"],
            project_root=None,
        )
        resolved, _ = resolve_modalities(PlayOperator, narrative)
        ctx = ModalityContext(
            session=None,
            narrative=narrative,
            focus_node=narrative,
            operator_name="play",
            crawl_result=cr,
            params={},
            project_root=tmp,
        )
        contrib = collect_modality_crawl_contribution(resolved, ctx)
        pinned = cr.graph.pinned_ids
        for pin in contrib.extra_pins:
            if pin not in pinned:
                pinned.append(pin)
        apply_modality_crawl(cr, resolved, ctx)

        self.assertIn("rules.system", pinned)
        self.assertIn("rules.encounter", pinned)


if __name__ == "__main__":
    unittest.main()
