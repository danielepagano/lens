"""Play's auto-pins (``rpg_play_context``) and its share of type companions.

The companion mechanism itself is engine behaviour and is covered in
``lens/core/test/test_rules_companions.py``.  What is RPG-specific, and tested
here, is the pair of booklets every play beat is run against — plus the
guarantee that play did not *lose* companions when they moved out of the
modality.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import CrawlResult, CrawlSpec, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.modalities import (
    apply_modality_crawl,
    collect_modality_crawl_contribution,
    ensure_modalities_registered,
    resolve_modalities,
)
from lens.core.modalities.catalog.rpg_play_context import PLAY_AUTO_PINS
from lens.core.modalities.types import ModalityContext
from lens.core.narrative import NarrativeNode
from lens.core.storage import Storage
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


def _make_project(tmp: Path, *, kb: dict[str, str] | None = None) -> NarrativeNode:
    """Create a minimal rpg project; *kb* maps ``type.key`` ids to bodies."""
    (tmp / "lens.toml").write_text(
        '[project]\nnarrative = "test"\ndatasets = ["rpg"]\n'
        '[[llm]]\nbase_url = "https://api.example.com/v1"\nmodel = "test"\n'
    )
    narrative_dir = tmp / "narrative" / "test"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# test\n")
    (tmp / "knowledge").mkdir(exist_ok=True)

    for kb_id, body in (kb or {}).items():
        obj_type, key = kb_id.split(".", 1)
        type_dir = tmp / "knowledge" / obj_type
        type_dir.mkdir(parents=True, exist_ok=True)
        (type_dir / f"{key}.md").write_text(body if body.endswith("\n") else body + "\n")

    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True,
    )
    return NarrativeNode(narrative_root=narrative_dir, key_path=())


class TestPlayAutoPins(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_modalities_registered()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _init_repo(self.root)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self._tmp.cleanup()

    def _apply_play_modalities(
        self, cr: CrawlResult, narrative: NarrativeNode
    ) -> None:
        resolved, _ = resolve_modalities(PlayOperator, narrative)
        ctx = ModalityContext(
            session=None,
            narrative=narrative,
            focus_node=narrative,
            operator_name="play",
            crawl_result=cr,
            params={},
            project_root=self.root,
        )
        contrib = collect_modality_crawl_contribution(resolved, ctx)
        pinned = cr.graph.pinned_ids
        for pin in contrib.extra_pins:
            if pin not in pinned:
                pinned.append(pin)
        apply_modality_crawl(cr, resolved, ctx)

    def test_core_rules_are_auto_pinned_for_play(self) -> None:
        narrative = _make_project(self.root)
        cr = CrawlResult.from_text_fields(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["pc.alice"],
            project_root=self.root,
        )

        self._apply_play_modalities(cr, narrative)

        for pin in PLAY_AUTO_PINS:
            self.assertIn(pin, cr.pinned_ids)

    def test_auto_pins_use_context_project_root(self) -> None:
        """Auto-pins apply even when ``CrawlResult.project_root`` is unset."""
        narrative = _make_project(self.root)
        cr = CrawlResult.from_text_fields(
            knowledge=[],
            previous_summaries=[],
            current_content=None,
            pinned_ids=["encounter.bridge"],
            project_root=None,
        )

        self._apply_play_modalities(cr, narrative)

        for pin in PLAY_AUTO_PINS:
            self.assertIn(pin, cr.pinned_ids)

    def test_auto_pins_are_play_only(self) -> None:
        """The two booklets are RPG-specific; no other operator pays for them."""
        narrative = _make_project(self.root)
        ctx = ModalityContext(
            session=None,
            narrative=narrative,
            focus_node=narrative,
            operator_name="write",
            crawl_result=None,
            params={},
            project_root=self.root,
        )
        resolved, _ = resolve_modalities(PlayOperator, narrative)

        contrib = collect_modality_crawl_contribution(resolved, ctx)

        for pin in PLAY_AUTO_PINS:
            self.assertNotIn(pin, contrib.extra_pins)

    def test_play_still_gets_type_companions_through_the_crawl(self) -> None:
        """Companions moved to the engine — play must not have lost them."""
        narrative = _make_project(
            self.root,
            kb={
                "encounter.bridge": "A collapsing rope bridge.",
                "rules.encounter": "Rules for encounter",
            },
        )

        cr = crawl(
            CrawlSpec.of(
                narrative,
                operator=PlayOperator,
                storage=Storage(self.root),
                extra_pins=["encounter.bridge"],
            )
        )

        self.assertIn("rules.encounter", cr.pinned_ids)
        self.assertTrue(any("Rules for encounter" in k for k in cr.knowledge))

    def test_auto_pinned_rules_do_not_pull_a_companion_of_their_own(self) -> None:
        """``rules.*`` never recurses — ``rules.rules`` is not a thing."""
        narrative = _make_project(self.root, kb={"rules.rules": "never wanted"})

        cr = crawl(
            CrawlSpec.of(
                narrative,
                operator=PlayOperator,
                storage=Storage(self.root),
            )
        )

        self.assertNotIn("rules.rules", cr.pinned_ids)


if __name__ == "__main__":
    unittest.main()
