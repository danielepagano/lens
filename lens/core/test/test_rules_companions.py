"""`rules.<type>` companions — engine behaviour, on every crawl-based operator.

Two layers: the transform in isolation (which routes put an object "in scope"),
and :func:`~lens.core.context.crawl` itself, where the guarantee that matters
lives — ``write``, ``chat`` and ``design`` all get the companion, not just
``play``.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import (
    CrawlResult,
    CrawlSpec,
    apply_transforms_to_result,
    crawl,
)
from lens.core.crawl_graph import RenderEffect
from lens.core.crawl_transforms import RulesCompanionTransform
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.modalities import ensure_modalities_registered
from lens.core.narrative import NarrativeNode
from lens.core.operators.chat import ChatOperator
from lens.core.operators.design import DesignOperator
from lens.core.operators.write import WriteOperator
from lens.core.storage import Storage


def _git(tmp: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp, capture_output=True, check=True)


def _init_repo(tmp: Path) -> Path:
    _git(tmp, "init")
    _git(tmp, "config", "user.email", "test@test.com")
    _git(tmp, "config", "user.name", "Test")
    (tmp / ".gitkeep").write_text("")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-m", "init")
    return tmp


def _make_project(tmp: Path, kb: dict[str, str] | None = None) -> NarrativeNode:
    """Minimal project; *kb* maps ``type.key`` ids to bodies."""
    (tmp / "lens.toml").write_text(
        '[project]\nnarrative = "test"\n'
        '[[llm]]\nbase_url = "https://api.example.com/v1"\nmodel = "test"\n'
    )
    narrative_dir = tmp / "narrative" / "test"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# test\n\nThe bridge is out.\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    for kb_id, body in (kb or {}).items():
        obj_type, key = kb_id.split(".", 1)
        type_dir = tmp / "knowledge" / obj_type
        type_dir.mkdir(parents=True, exist_ok=True)
        (type_dir / f"{key}.md").write_text(body if body.endswith("\n") else body + "\n")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-m", "project")
    return NarrativeNode(narrative_root=narrative_dir, key_path=())


class _CompanionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_modalities_registered()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _init_repo(Path(self._tmp.name))
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self._tmp.cleanup()


class TestRulesCompanionTransform(_CompanionTestCase):
    """Which routes into scope pull a companion (transform in isolation)."""

    def _result(
        self,
        *,
        knowledge: list[str],
        pinned_ids: list[str],
        effects: list[RenderEffect] | None = None,
        project_root: Path | None = None,
    ) -> CrawlResult:
        cr = CrawlResult.from_text_fields(
            knowledge=knowledge,
            previous_summaries=[],
            current_content=None,
            pinned_ids=pinned_ids,
            project_root=project_root if project_root is not None else self.root,
        )
        for effect in effects or []:
            cr.graph.add_effect(effect)
        apply_transforms_to_result(
            cr,
            [
                RulesCompanionTransform(
                    project_root=self.root, storage=Storage(self.root)
                )
            ],
        )
        return cr

    def test_injects_rules_for_pinned_encounter(self) -> None:
        """When encounter.foo is pinned and rules.encounter exists, inject it."""
        _make_project(self.root, {"rules.encounter": "Rules for encounter"})

        cr = self._result(
            knowledge=["existing KB"], pinned_ids=["pc.alice", "encounter.bridge"]
        )

        self.assertIn("rules.encounter", cr.pinned_ids)
        self.assertTrue(
            any("Rules for encounter" in k for k in cr.knowledge),
            f"rules.encounter content not found in knowledge: {cr.knowledge}",
        )

    def test_no_injection_when_rules_missing(self) -> None:
        """When encounter.foo is pinned but rules.encounter doesn't exist, skip."""
        _make_project(self.root)

        cr = self._result(knowledge=[], pinned_ids=["pc.alice", "encounter.bridge"])

        self.assertNotIn("rules.encounter", cr.pinned_ids)

    def test_no_duplicate_when_already_pinned(self) -> None:
        """When rules.encounter is already pinned, don't add it again."""
        _make_project(self.root, {"rules.encounter": "Rules for encounter"})

        cr = self._result(
            knowledge=["already here"],
            pinned_ids=["rules.encounter", "encounter.bridge"],
        )

        self.assertEqual(cr.pinned_ids.count("rules.encounter"), 1)
        self.assertEqual(len(cr.knowledge), 1)

    def test_multiple_types(self) -> None:
        """Multiple pinned types each get their rules companion if it exists."""
        _make_project(
            self.root,
            {"rules.encounter": "Rules for encounter", "rules.front": "Rules for front"},
        )

        cr = self._result(
            knowledge=[], pinned_ids=["pc.alice", "encounter.bridge", "front.doom"]
        )

        self.assertIn("rules.encounter", cr.pinned_ids)
        self.assertIn("rules.front", cr.pinned_ids)
        self.assertEqual(len(cr.knowledge), 2)

    def test_rules_objects_dont_trigger_recursion(self) -> None:
        """Pinned rules.* objects don't trigger lookup for rules.rules."""
        _make_project(self.root, {"rules.rules": "never wanted"})

        cr = self._result(knowledge=[], pinned_ids=["pc.alice", "rules.system"])

        self.assertNotIn("rules.rules", cr.pinned_ids)
        self.assertEqual(len(cr.knowledge), 0)

    def test_injects_rules_for_a_mentioned_object(self) -> None:
        """An ``@`` mention is in scope without being a pin — it still needs rules.

        Someone reaching for ``@stat.wolf`` mid-scene is exactly when the model
        most needs to be told how to run one.
        """
        _make_project(self.root, {"rules.stat": "Rules for stat"})

        cr = self._result(
            knowledge=[],
            pinned_ids=["pc.alice"],
            effects=[
                RenderEffect(
                    kind="kb-mention",
                    token="stat.wolf",
                    result="120",
                    source_component_id="legacy-current",
                )
            ],
        )

        self.assertIn("rules.stat", cr.pinned_ids)
        self.assertTrue(any("Rules for stat" in k for k in cr.knowledge))

    def test_injects_rules_for_an_included_object(self) -> None:
        """``include`` is how a loaded module latches; same scope, same rules."""
        _make_project(self.root, {"rules.tracker": "Rules for tracker"})

        cr = self._result(
            knowledge=[],
            pinned_ids=["pc.alice"],
            effects=[
                RenderEffect(
                    kind="kb-include",
                    token="tracker.bridge-fight",
                    result="200",
                    source_component_id="legacy-current",
                )
            ],
        )

        self.assertIn("rules.tracker", cr.pinned_ids)

    def test_injects_rules_for_an_inline_expanded_object(self) -> None:
        """``kb-inline`` carries the resolved id in ``result``, not ``token``."""
        _make_project(self.root, {"rules.stat": "Rules for stat"})

        cr = self._result(
            knowledge=[],
            pinned_ids=["pc.alice"],
            effects=[
                RenderEffect(
                    kind="kb-inline",
                    token="@stat.wolf",
                    result="stat.wolf",
                    source_component_id="legacy-current",
                )
            ],
        )

        self.assertIn("rules.stat", cr.pinned_ids)

    def test_mentioned_rules_object_is_not_duplicated(self) -> None:
        """A booklet already mentioned into scope is not added a second time."""
        _make_project(self.root, {"rules.stat": "Rules for stat"})

        cr = self._result(
            knowledge=[],
            pinned_ids=["stat.wolf"],
            effects=[
                RenderEffect(
                    kind="kb-include",
                    token="rules.stat",
                    result="120",
                    source_component_id="legacy-current",
                )
            ],
        )

        self.assertNotIn("rules.stat", cr.pinned_ids)
        self.assertEqual(cr.knowledge, [])

    def test_uses_the_transform_project_root_not_the_results(self) -> None:
        """Companions resolve even when ``CrawlResult.project_root`` is unset."""
        _make_project(self.root, {"rules.encounter": "Rules for encounter"})

        cr = self._result(
            knowledge=[], pinned_ids=["encounter.bridge"], project_root=None
        )

        self.assertIn("rules.encounter", cr.pinned_ids)


class TestRulesCompanionsInCrawl(_CompanionTestCase):
    """The generalization: every crawl-based operator, not only ``play``."""

    def _crawl(
        self,
        operator: type,
        narrative: NarrativeNode,
        *,
        extra_pins: list[str] | None = None,
        modules: list[str] | None = None,
    ) -> CrawlResult:
        spec = CrawlSpec.of(
            narrative,
            operator=operator,
            storage=Storage(self.root),
            extra_pins=extra_pins,
            modules=modules,
        )
        return crawl(spec)

    def test_write_pulls_the_companion_for_a_pinned_object(self) -> None:
        narrative = _make_project(
            self.root,
            {
                "encounter.bridge": "A collapsing rope bridge.",
                "rules.encounter": "Rules for encounter",
            },
        )

        cr = self._crawl(WriteOperator, narrative, extra_pins=["encounter.bridge"])

        self.assertIn("rules.encounter", cr.pinned_ids)
        self.assertTrue(any("Rules for encounter" in k for k in cr.knowledge))

    def test_chat_pulls_the_companion_for_a_pinned_object(self) -> None:
        narrative = _make_project(
            self.root,
            {
                "npc.smith": "The village smith.",
                "rules.npc": "Rules for npc",
            },
        )

        cr = self._crawl(ChatOperator, narrative, extra_pins=["npc.smith"])

        self.assertIn("rules.npc", cr.pinned_ids)
        self.assertTrue(any("Rules for npc" in k for k in cr.knowledge))

    def test_design_pulls_the_companion_for_a_pinned_object(self) -> None:
        narrative = _make_project(
            self.root,
            {
                "front.doom": "The doom clock.",
                "rules.front": "Rules for front",
            },
        )

        cr = self._crawl(DesignOperator, narrative, extra_pins=["front.doom"])

        self.assertIn("rules.front", cr.pinned_ids)

    def test_companion_is_attributed_to_the_transform(self) -> None:
        """`lens explain` reads the component id and effect; both must be set."""
        narrative = _make_project(
            self.root,
            {
                "encounter.bridge": "A collapsing rope bridge.",
                "rules.encounter": "Rules for encounter",
            },
        )

        cr = self._crawl(WriteOperator, narrative, extra_pins=["encounter.bridge"])

        component = cr.graph.component_by_id("rules-companion:rules.encounter")
        self.assertIsNotNone(component)
        assert component is not None
        self.assertEqual(component.kind, "knowledge")
        self.assertEqual(component.metadata.get("kb_id"), "rules.encounter")
        self.assertTrue(
            any(effect.kind == "rules-companion" for effect in cr.graph.effects)
        )

    def test_a_module_companion_is_not_added_twice(self) -> None:
        """``ModuleTransform`` resolves ``rules.<key>`` first; this must dedupe.

        ``design --module design.stat`` pulls ``rules.stat`` as the module's own
        companion.  ``stat._template`` then puts a ``stat.*`` object in scope,
        so the engine-wide pass wants ``rules.stat`` too — and must find it
        already pinned rather than render it a second time.
        """
        narrative = _make_project(
            self.root,
            {
                "design.stat": "How to author a stat block.",
                "stat._template": "Stat block template.",
                "rules.stat": "Rules for stat",
            },
        )

        cr = self._crawl(DesignOperator, narrative, modules=["design.stat"])

        self.assertEqual(cr.pinned_ids.count("rules.stat"), 1)
        self.assertEqual(
            [k for k in cr.knowledge if "Rules for stat" in k].__len__(),
            1,
            f"rules.stat rendered more than once: {cr.knowledge}",
        )
        self.assertIsNone(cr.graph.component_by_id("rules-companion:rules.stat"))

    def test_no_companion_without_the_file(self) -> None:
        """Nothing to ship, nothing to pay for."""
        narrative = _make_project(
            self.root, {"encounter.bridge": "A collapsing rope bridge."}
        )

        cr = self._crawl(WriteOperator, narrative, extra_pins=["encounter.bridge"])

        self.assertNotIn("rules.encounter", cr.pinned_ids)


if __name__ == "__main__":
    unittest.main()
