"""Unit tests for lens.context: crawl and assemble_prompt."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import (
    CrawlResult,
    CrawlSpec,
    SliceAnchor,
    collect_vars,
    spine_path,
    assemble_prompt,
    assemble_prompt_kb_edit,
    crawl,
    crawl_result_from_pins,
)
from lens.core.narrative import NarrativeNode


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
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    kb_dir = tmp / "knowledge"
    kb_dir.mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp, capture_output=True, check=True,
    )
    node = NarrativeNode(narrative_root=narrative_dir, key_path=())
    return tmp, node


def _add_kb(root: Path, type_name: str, key: str, content: str) -> None:
    path = root / "knowledge" / type_name / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"kb {type_name}.{key}"], cwd=root, capture_output=True, check=True)


class TestCrawlNoPins(unittest.TestCase):
    def test_empty_knowledge_when_no_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _root, node = _make_project(_init_repo(Path(tmp)))
            r = crawl(node)
            self.assertEqual(r.knowledge, [])


class TestCrawlPinOrder(unittest.TestCase):
    def test_pins_from_root_before_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "a", "Place A")
            _add_kb(root, "place", "b", "Place B")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.a\n]: #\n\n# test\n")
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  kb_pin:\n    - place.b\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            child = node.child_node("ch1")
            r = crawl(child)
            self.assertEqual(len(r.knowledge), 2)
            self.assertIn("place.a", r.knowledge[0])
            self.assertIn("place.b", r.knowledge[1])
            self.assertEqual(r.pinned_ids, ["place.a", "place.b"])
            self.assertEqual(r.remember_pins, {})

    def test_remember_pins_populated_on_crawl(self) -> None:
        """Crawl attaches remember_pins for pinned ids that have remember.* tags."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "lore", "alice", "Alice")
            from lens.core.knowledge import KnowledgeStore
            from lens.core.media import MediaService

            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            kb = KnowledgeStore.for_project(root)
            self.assertIsNone(kb.add_tags("lore.alice", ["remember.session-notes", "other"]))
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - lore.alice\n]: #\n\n# test\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "fm"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            r = crawl(node, include_narrative=False)
            self.assertEqual(r.pinned_ids, ["lore.alice"])
            self.assertEqual(
                r.remember_pins,
                {"lore.alice": ["remember.session-notes"]},
            )

    def test_linked_expansion_preserves_pinning_order(self) -> None:
        """Crawl with + pin: explicit id before linked, and pinning order across levels."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "market", "The market")
            _add_kb(root, "person", "amy", "Amy")
            from lens.core.knowledge import KnowledgeStore
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("person.amy", ["place.market"])
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - person.amy+\n]: #\n\n# test\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            r = crawl(node)
            self.assertEqual(len(r.knowledge), 2)
            self.assertIn("person.amy", r.knowledge[0])
            self.assertIn("place.market", r.knowledge[1])


class TestCrawlUnpin(unittest.TestCase):
    def test_unpin_at_child_cancels_ancestor_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "x", "Place X")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.x\n]: #\n\n# test\n")
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  kb_unpin:\n    - place.x\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            child = node.child_node("ch1")
            r = crawl(child)
            self.assertEqual(r.knowledge, [])

    def test_unpin_at_ancestor_does_not_cancel_descendant_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "x", "Place X")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.x\n  kb_unpin:\n    - place.x\n]: #\n\n# test\n")
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  kb_pin:\n    - place.x\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            child = node.child_node("ch1")
            r = crawl(child)
            self.assertEqual(len(r.knowledge), 1)
            self.assertIn("place.x", r.knowledge[0])


class TestCrawlDedup(unittest.TestCase):
    def test_same_id_pinned_multiple_levels_appears_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "a", "Place A")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.a\n]: #\n\n# test\n")
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  kb_pin:\n    - place.a\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            child = node.child_node("ch1")
            r = crawl(child)
            self.assertEqual(len(r.knowledge), 1)


class TestCrawlExtraPins(unittest.TestCase):
    def test_extra_pins_override_ancestor_unpins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "x", "Place X")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_unpin:\n    - place.x\n]: #\n\n# test\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            r = crawl(node, extra_pins=["place.x"])
            self.assertEqual(len(r.knowledge), 1)


class TestCrawlFacets(unittest.TestCase):
    """Facet expansion on ``-``: implicit, root-pins-only, operator-gated.

    See ``KnowledgeStore.list_facet_ids`` and the ``expand_facets`` handling
    in ``_resolve_pins_for_ancestors`` / ``crawl``.
    """

    def _component_metadata(self, r: CrawlResult, kb_id: str) -> dict[str, str]:
        for component in r.graph.components:
            if component.metadata.get("kb_id") == kb_id:
                return component.metadata
        raise AssertionError(f"no knowledge component for {kb_id!r}")

    def test_design_crawl_gets_facet_of_root_pin(self) -> None:
        from lens.core.operators.design import DesignOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            _add_kb(root, "front", "problem-prep", "Prep notes.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem\n]: #\n\n# test\n"
            )
            _commit(root)
            r = crawl(node, operator=DesignOperator)
            self.assertEqual(r.pinned_ids, ["front.problem", "front.problem-prep"])

    def test_advance_crawl_gets_facet_of_root_pin(self) -> None:
        from lens.rpg.operators.advance import AdvanceOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            _add_kb(root, "front", "problem-prep", "Prep notes.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem\n]: #\n\n# test\n"
            )
            _commit(root)
            r = crawl(node, operator=AdvanceOperator)
            self.assertEqual(r.pinned_ids, ["front.problem", "front.problem-prep"])

    def test_play_crawl_does_not_get_facet(self) -> None:
        from lens.rpg.operators.play import PlayOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            _add_kb(root, "front", "problem-prep", "Prep notes.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem\n]: #\n\n# test\n"
            )
            _commit(root)
            r = crawl(node, operator=PlayOperator)
            self.assertEqual(r.pinned_ids, ["front.problem"])

    def test_write_crawl_does_not_get_facet(self) -> None:
        """No ``operator`` set at all (write's usual crawl shape) is also unaffected."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            _add_kb(root, "front", "problem-prep", "Prep notes.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem\n]: #\n\n# test\n"
            )
            _commit(root)
            r = crawl(node)
            self.assertEqual(r.pinned_ids, ["front.problem"])

    def test_facet_of_plus_linked_object_not_pulled_in(self) -> None:
        """The 14-collision case: a facet-shaped id reached only via ``+`` link
        expansion (never as a root pin) must not gain its own facets."""
        from lens.core.operators.design import DesignOperator
        from lens.core.knowledge import KnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "party", "roster", "The roster.")
            _add_kb(root, "stat", "guard", "A guard.")
            _add_kb(root, "stat", "guard-captain", "An unrelated monster stat block.")
            KnowledgeStore.clear_registry()
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("party.roster", ["stat.guard"])
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - party.roster+\n]: #\n\n# test\n"
            )
            _commit(root)
            KnowledgeStore.clear_registry()
            r = crawl(node, operator=DesignOperator)
            self.assertEqual(
                sorted(r.pinned_ids), ["party.roster", "stat.guard"]
            )
            self.assertNotIn("stat.guard-captain", r.pinned_ids)

    def test_root_pin_with_plus_gets_both_facets_and_links(self) -> None:
        from lens.core.operators.design import DesignOperator
        from lens.core.knowledge import KnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            _add_kb(root, "front", "problem-prep", "Prep notes.")
            _add_kb(root, "person", "villain", "The villain.")
            KnowledgeStore.clear_registry()
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("front.problem", ["person.villain"])
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem+\n]: #\n\n# test\n"
            )
            _commit(root)
            KnowledgeStore.clear_registry()
            r = crawl(node, operator=DesignOperator)
            self.assertEqual(
                sorted(r.pinned_ids),
                ["front.problem", "front.problem-prep", "person.villain"],
            )

    def test_explicit_unpin_of_facet_suppresses_it(self) -> None:
        from lens.core.operators.design import DesignOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            _add_kb(root, "front", "problem-prep", "Prep notes.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem\n"
                "  kb_unpin:\n    - front.problem-prep\n]: #\n\n# test\n"
            )
            _commit(root)
            r = crawl(node, operator=DesignOperator)
            self.assertEqual(r.pinned_ids, ["front.problem"])

    def test_multi_level_facet_arrives_for_root(self) -> None:
        from lens.core.operators.design import DesignOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            _add_kb(root, "front", "problem-prep", "Prep notes.")
            _add_kb(root, "front", "problem-prep-notes", "Deeper notes.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem\n]: #\n\n# test\n"
            )
            _commit(root)
            r = crawl(node, operator=DesignOperator)
            self.assertEqual(
                r.pinned_ids,
                ["front.problem", "front.problem-prep", "front.problem-prep-notes"],
            )

    def test_object_with_no_facets_is_unaffected(self) -> None:
        from lens.core.operators.design import DesignOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem\n]: #\n\n# test\n"
            )
            _commit(root)
            r = crawl(node, operator=DesignOperator)
            self.assertEqual(r.pinned_ids, ["front.problem"])

    def test_module_pin_gets_its_facet(self) -> None:
        """``--module`` names an id directly, so it is a root pin.

        The transform that resolves modules bypasses ``_resolve_pins_for_ancestors``
        entirely, so facet expansion had to be wired into it separately — it was
        documented as working before it did.
        """
        from lens.core.operators.design import DesignOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "design", "front", "[DESIGN MODULE]: FRONT")
            _add_kb(root, "design", "front-extra", "Prep-side addendum.")
            r = crawl(node, operator=DesignOperator, modules=("design.front",))
            self.assertIn("design.front-extra", r.pinned_ids)

    def test_play_module_pin_does_not_get_facet(self) -> None:
        """Facet expansion stays operator-gated on the module route too."""
        from lens.rpg.operators.play import PlayOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "rules", "combat", "Combat rules.")
            _add_kb(root, "rules", "combat-optional", "Unrelated variant rules.")
            r = crawl(node, operator=PlayOperator, modules=("rules.combat",))
            self.assertNotIn("rules.combat-optional", r.pinned_ids)

    def test_module_link_target_does_not_get_facet(self) -> None:
        """A module's ``+`` link target is not a root pin, so it gains no facets.

        Same collision guard as the pin route: ``design.encounter`` linking
        ``stat.guard`` must not drag in ``stat.guard-captain``.
        """
        from lens.core.operators.design import DesignOperator
        from lens.core.knowledge import KnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "design", "encounter", "[DESIGN MODULE]: ENCOUNTER")
            _add_kb(root, "stat", "guard", "A guard.")
            _add_kb(root, "stat", "guard-captain", "An unrelated captain.")
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("design.encounter", ["stat.guard"])
            _commit(root)
            KnowledgeStore.clear_registry()
            r = crawl(node, operator=DesignOperator, modules=("design.encounter",))
            self.assertIn("stat.guard", r.pinned_ids)
            self.assertNotIn("stat.guard-captain", r.pinned_ids)

    def test_id_pinned_and_also_plus_expanded_renders_once(self) -> None:
        """An id reachable both ways must not render its KB block twice.

        ``timeline.vale+`` pulls ``front.blight``; pinning ``front.blight`` at
        the cursor (to get its facets) named the same id again and duplicated
        the whole block in the prompt.
        """
        from lens.core.operators.design import DesignOperator
        from lens.core.knowledge import KnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "timeline", "vale", "Day: 1")
            _add_kb(root, "front", "blight", "The blight.")
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("timeline.vale", ["front.blight"])
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - timeline.vale+\n]: #\n\n# test\n"
            )
            _commit(root)
            KnowledgeStore.clear_registry()
            r = crawl(node, operator=DesignOperator, extra_pins=["front.blight"])
            self.assertEqual(r.pinned_ids.count("front.blight"), 1)
            blocks = "\n".join(r.knowledge)
            self.assertEqual(blocks.count("KB['front.blight']"), 1)

    def test_facet_provenance_metadata(self) -> None:
        from lens.core.operators.design import DesignOperator

        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "front", "problem", "The problem.")
            _add_kb(root, "front", "problem-prep", "Prep notes.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - front.problem\n]: #\n\n# test\n"
            )
            _commit(root)
            r = crawl(node, operator=DesignOperator)

            parent_meta = self._component_metadata(r, "front.problem")
            facet_meta = self._component_metadata(r, "front.problem-prep")

            self.assertNotIn("facet_of", parent_meta)
            self.assertEqual(facet_meta.get("facet_of"), "front.problem")
            # The facet carries the parent's origin fields (same ancestor pin).
            self.assertEqual(
                facet_meta.get("pin_source"), parent_meta.get("pin_source")
            )
            self.assertEqual(
                facet_meta.get("pin_node"), parent_meta.get("pin_node")
            )
            self.assertEqual(facet_meta.get("pin_raw"), "front.problem")

            for component in r.graph.components:
                if component.metadata.get("kb_id") == "front.problem-prep":
                    assert component.source is not None
                    self.assertEqual(
                        component.source.metadata.get("facet_of"), "front.problem"
                    )


def _write_node(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _commit(root: Path, msg: str = "update") -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=root, capture_output=True, check=True)


class TestCrawlNarrative(unittest.TestCase):
    def test_narrative_segments_root_to_cursor_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("# test\n\n[section:ch1]: #\n\nRoot content.")
            _write_node(node.narrative_root / "ch1" / "_node.md",
                "# ch1\n\n[write\n  prompt: x\n]: #\n\nChild content.")
            _commit(root)
            r = crawl(node.child_node("ch1"))
            self.assertEqual(len(r.previous_summaries), 1)
            self.assertIn("Root content", r.previous_summaries[0])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Child content", r.current_content)
            self.assertNotIn("[write", r.current_content)
            self.assertNotIn("[section", r.previous_summaries[0])

    def test_three_levels_root_to_leaf(self) -> None:
        """Root → chapter → scene: crawling from the leaf yields all three segments."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text(
                "# campaign\n\n[section:ch1]: #\n\nCampaign overview."
            )
            _write_node(node.narrative_root / "ch1" / "_node.md",
                "# ch1\n\n[section:scene1]: #\n\nChapter one summary.")
            _write_node(node.narrative_root / "ch1" / "scene1" / "_node.md",
                "# scene1\n\nScene one prose.")
            _commit(root)
            leaf = node.child_node("ch1").child_node("scene1")
            r = crawl(leaf)
            self.assertEqual(len(r.previous_summaries), 2)
            self.assertIn("Campaign overview", r.previous_summaries[0])
            self.assertIn("Chapter one", r.previous_summaries[1])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Scene one prose", r.current_content)

    def test_crawl_from_middle_node_excludes_deeper_children(self) -> None:
        """Crawling from a mid-tree node only includes root and that node, not its children."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("# campaign\n\nCampaign text.")
            _write_node(node.narrative_root / "ch1" / "_node.md",
                "# ch1\n\nChapter text.")
            _write_node(node.narrative_root / "ch1" / "scene1" / "_node.md",
                "# scene1\n\nScene text.")
            _commit(root)
            mid = node.child_node("ch1")
            r = crawl(mid)
            self.assertEqual(len(r.previous_summaries), 1)
            self.assertIn("Campaign text", r.previous_summaries[0])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Chapter text", r.current_content)
            all_text = "\n".join(r.previous_summaries) + (r.current_content or "")
            self.assertNotIn("Scene text", all_text)

    def test_crawl_from_root_only_has_one_segment(self) -> None:
        """Crawling from the root node yields only the root segment."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("# campaign\n\nRoot only.")
            _write_node(node.narrative_root / "ch1" / "_node.md", "# ch1\n\nChild text.")
            _commit(root)
            r = crawl(node)
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Root only", r.current_content)

    def test_comments_stripped_at_all_levels(self) -> None:
        """Front matter, section tags, and write annotations are all stripped across levels."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text(
                "[\n  kb_pin: []\n]: #\n\n# campaign\n\n[section:ch1]: #\n\nRoot text."
            )
            _write_node(node.narrative_root / "ch1" / "_node.md",
                "[\n  kb_pin: []\n]: #\n\n# ch1\n\n[write]: #\n\nChild text.\n\n[/write]: #")
            _commit(root)
            r = crawl(node.child_node("ch1"))
            all_segs = r.previous_summaries + ([r.current_content] if r.current_content else [])
            for seg in all_segs:
                self.assertNotIn("]: #", seg)
                self.assertNotIn("kb_pin", seg)
            self.assertEqual(len(r.previous_summaries), 1)
            self.assertIn("Root text", r.previous_summaries[0])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Child text", r.current_content)

    def test_open_cursor_annotation_at_tail_stripped(self) -> None:
        """An unclosed section annotation at the end (the cursor marker) is stripped."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text(
                "# campaign\n\nRoot text.\n\n[section:ch1]: #\n"
            )
            _commit(root)
            r = crawl(node)
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Root text", r.current_content)
            self.assertNotIn("[section", r.current_content)

    def test_empty_nodes_skipped(self) -> None:
        """Nodes whose content is entirely comments/whitespace do not produce a segment."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("[\n  kb_pin: []\n]: #\n")
            _write_node(node.narrative_root / "ch1" / "_node.md", "# ch1\n\nChild text.")
            _commit(root)
            r = crawl(node.child_node("ch1"))
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Child text", r.current_content)

    def test_include_narrative_false_skips_narrative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("# campaign\n\nSome text.")
            _commit(root)
            r = crawl(node, include_narrative=False)
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNone(r.current_content)


class TestCrawlMissingKb(unittest.TestCase):
    def test_missing_objects_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "a", "Place A")
            md = node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.a\n    - place.nonexistent\n]: #\n\n# test\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            r = crawl(node)
            self.assertEqual(len(r.knowledge), 1)
            self.assertIn("place.a", r.knowledge[0])
            # pinned_ids is parallel to knowledge — missing objects are excluded from both
            self.assertEqual(r.pinned_ids, ["place.a"])


class TestChatParticipantPinExpansion(unittest.TestCase):
    def test_chat_participant_loads_linked_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "companion", "x", "Companion sheet.")
            _add_kb(root, "memory", "x-psyche", "Psyche profile.")
            _add_kb(root, "human", "y", "Human sheet.")
            from lens.core.knowledge import KnowledgeStore
            from lens.core.media import MediaService

            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            kb = KnowledgeStore.for_project(root)
            self.assertIsNone(kb.add_tags("companion.x", ["memory.x-psyche"]))
            slug = "chat-sess"
            node.md_path().write_text(
                f"# test\n\n[chat:{slug}\n"
                "    as_kb_id: companion.x\n"
                "    with_kb_id: human.y\n"
                "]: #\n",
                encoding="utf-8",
            )
            sess_dir = node.narrative_root / slug
            sess_dir.mkdir()
            (sess_dir / "_node.md").write_text(f"# {slug}\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "chat session"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            child = node.child_node(slug)
            r = crawl(child, include_narrative=False)
            self.assertIn("companion.x", r.pinned_ids)
            self.assertIn("memory.x-psyche", r.pinned_ids)
            self.assertIn("human.y", r.pinned_ids)
            joined = "\n".join(r.knowledge)
            self.assertIn("memory.x-psyche", joined)
            self.assertIn("Psyche profile.", joined)

    def test_chat_participant_second_level_links_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "companion", "x", "Companion.")
            _add_kb(root, "memory", "x-psyche", "Psyche.")
            _add_kb(root, "memory", "x-deep", "Deep link.")
            _add_kb(root, "human", "y", "Human.")
            from lens.core.knowledge import KnowledgeStore
            from lens.core.media import MediaService

            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            kb = KnowledgeStore.for_project(root)
            self.assertIsNone(kb.add_tags("companion.x", ["memory.x-psyche"]))
            self.assertIsNone(kb.add_tags("memory.x-psyche", ["memory.x-deep"]))
            slug = "chat-sess"
            node.md_path().write_text(
                f"# test\n\n[chat:{slug}\n"
                "    as_kb_id: companion.x\n"
                "    with_kb_id: human.y\n"
                "]: #\n",
                encoding="utf-8",
            )
            sess_dir = node.narrative_root / slug
            sess_dir.mkdir()
            (sess_dir / "_node.md").write_text(f"# {slug}\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "chat session"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            child = node.child_node(slug)
            r = crawl(child, include_narrative=False)
            self.assertIn("companion.x", r.pinned_ids)
            self.assertIn("memory.x-psyche", r.pinned_ids)
            self.assertNotIn("memory.x-deep", r.pinned_ids)


class TestAssemblePrompt(unittest.TestCase):
    def test_returns_system_and_user_messages(self) -> None:
        result = CrawlResult.from_text_fields(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt(
            result,
            system_prompt="You are helpful.",
            instruction="Do the task.",
        )
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[0]["content"], "You are helpful.")
        self.assertEqual(msgs[1]["role"], "user")
        self.assertIn("TASK", msgs[1]["content"])
        self.assertIn("Do the task.", msgs[1]["content"])

    def test_omits_kb_block_when_empty(self) -> None:
        result = CrawlResult.from_text_fields(knowledge=[], previous_summaries=[], current_content="# test")
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Task",
        )
        self.assertNotIn("KNOWLEDGE", msgs[1]["content"])

    def test_omits_narrative_blocks_when_empty(self) -> None:
        result = CrawlResult.from_text_fields(knowledge=["KB[place.a]"], previous_summaries=[], current_content=None)
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Task",
        )
        self.assertNotIn("PREVIOUS EVENTS SUMMARY", msgs[1]["content"])
        self.assertNotIn("CURRENT PASSAGE", msgs[1]["content"])

    def test_includes_kb_and_current_passage_when_present(self) -> None:
        result = CrawlResult.from_text_fields(
            knowledge=["KB['place.a']\ncontent"],
            previous_summaries=[],
            current_content="# test\n\nprose",
        )
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Task",
        )
        content = msgs[1]["content"]
        self.assertIn("KNOWLEDGE", content)
        self.assertIn("CURRENT PASSAGE", content)
        self.assertIn("place.a", content)
        self.assertIn("prose", content)

    def test_previous_summaries_and_current_passage_use_distinct_blocks(self) -> None:
        result = CrawlResult.from_text_fields(
            knowledge=[],
            previous_summaries=["Earlier summary."],
            current_content="Current prose.",
        )
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Task",
        )
        content = msgs[1]["content"]
        self.assertIn("PREVIOUS EVENTS SUMMARY", content)
        self.assertIn("CURRENT PASSAGE", content)
        self.assertIn("Earlier summary.", content)
        self.assertIn("Current prose.", content)

    def test_ai_secret_sections_decoded_in_prompt(self) -> None:
        result = CrawlResult.from_text_fields(
            knowledge=[],
            previous_summaries=[],
            current_content=(
                "Visible prose.\n\n"
                "<!-- ai:secret:\ngur frperg vf va gur pbagrag\n-->"
            ),
        )
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Continue.",
        )
        content = msgs[1]["content"]
        self.assertIn("the secret is in the content", content)
        self.assertIn("<!-- ai:secret:", content)
        self.assertNotIn("gur frperg vf va gur pbagrag", content)


class TestCrawlGraphExpansion(unittest.TestCase):
    def test_inline_kb_mention_replaces_instruction_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "visual", "person-amy", "red cloak, silver hair")
            from lens.core.knowledge import KnowledgeStore
            from lens.core.media import MediaService

            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            kb = KnowledgeStore.for_project(root)
            self.assertIsNone(kb.add_tags("visual.person-amy", ["inline"]))
            _commit(root, "tag inline")
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()

            result = crawl(node, include_narrative=False)
            msgs = assemble_prompt(
                result,
                system_prompt="Render an image.",
                instruction="@visual.person-amy standing at sunset",
            )

            content = "\n\n".join(m["content"] for m in msgs)
            self.assertIn("red cloak, silver hair standing at sunset", content)
            self.assertNotIn("@visual.person-amy", content)
            self.assertTrue(any(e.kind == "kb-inline" for e in result.render_effects))

    def test_reference_kb_mention_in_task_adds_no_knowledge_block(self) -> None:
        """A bare `@` in rendered text no longer pulls the object into context.

        Scope is added by the ``[mention: …]: #`` annotation a command writes,
        which expands at its own line — not by scanning rendered text, which
        could never expire and invalidated the whole cacheable prefix.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "Amy is a hero.")

            result = crawl(node, include_narrative=False)
            msgs = assemble_prompt(
                result,
                system_prompt="Write.",
                instruction="Use @person.amy as context.",
            )

            self.assertNotIn("RELEVANT KNOWLEDGE", msgs[1]["content"])
            self.assertNotIn("KB['person.amy']", msgs[1]["content"])
            self.assertIn("@person.amy", msgs[1]["content"])
            self.assertFalse(any(e.kind == "kb-reference" for e in result.render_effects))

    def test_rolls_in_kb_are_render_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "monster", "wolf", "Damage: @roll 2d6+2")
            node.md_path().write_text("[\n  kb_pin:\n    - monster.wolf\n]: #\n\n# test\n")
            _commit(root, "pin monster")

            result = crawl(node, include_narrative=False)

            self.assertEqual(len(result.knowledge), 1)
            self.assertIn("rolled 2d6+2=", result.knowledge[0])
            self.assertNotIn("@roll", result.knowledge[0])
            self.assertTrue(any(e.kind == "roll" for e in result.render_effects))

    def test_front_matter_vars_expand_in_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text(
                "[\n  vars:\n    mood: ominous and quiet\n]: #\n\n# test\n"
            )

            result = crawl(node, include_narrative=False)
            msgs = assemble_prompt(
                result,
                system_prompt="Write.",
                instruction="Make the scene @var:mood.",
            )

            self.assertIn("Make the scene ominous and quiet.", msgs[1]["content"])
            self.assertTrue(any(e.kind == "var" for e in result.render_effects))

    def test_collect_vars_inherits_root_to_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text(
                "[\n  vars:\n    mood: tense\n    color: red\n]: #\n\n# test\n"
            )
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  vars:\n    color: blue\n    weather: storm\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "vars"],
                cwd=root, capture_output=True, check=True,
            )
            child = node.child_node("ch1")

            vars_map = collect_vars(child)

            self.assertEqual(vars_map["mood"], "tense")
            self.assertEqual(vars_map["color"], "blue")
            self.assertEqual(vars_map["weather"], "storm")

    def test_verbose_llm_logging_writes_render_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            (root / "lens.toml").write_text(
                '[project]\nnarrative = "test"\nverbose_llm = true\n'
            )
            _add_kb(root, "monster", "wolf", "Damage: @roll 2d6+2")
            node.md_path().write_text(
                "[\n  kb_pin:\n    - monster.wolf\n]: #\n\n# test\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "verbose"],
                cwd=root, capture_output=True, check=True,
            )

            result = crawl(node, include_narrative=False)
            with self.assertLogs("lens.core.context", level="INFO") as caplog:
                assemble_prompt(
                    result,
                    system_prompt="Write.",
                    instruction="Encounter the wolf.",
                )

            self.assertTrue(
                any("[RENDER EFFECTS]" in record.getMessage() for record in caplog.records),
                f"no [RENDER EFFECTS] log in {[r.getMessage() for r in caplog.records]}",
            )


class TestCrawlResultFromPins(unittest.TestCase):
    def test_empty_pins_returns_empty_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            r = crawl_result_from_pins(root, [], [])
            self.assertEqual(r.knowledge, [])
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNone(r.current_content)

    def test_pins_resolved_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "Amy is a hero.")
            r = crawl_result_from_pins(root, ["person.amy"], [])
            self.assertEqual(len(r.knowledge), 1)
            self.assertIn("person.amy", r.knowledge[0])
            self.assertIn("Amy is a hero", r.knowledge[0])
            self.assertEqual(r.pinned_ids, ["person.amy"])

    def test_unpin_excludes_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "Amy")
            _add_kb(root, "place", "x", "Place X")
            r = crawl_result_from_pins(root, ["person.amy", "place.x"], ["place.x"])
            self.assertEqual(len(r.knowledge), 1)
            self.assertIn("person.amy", r.knowledge[0])
            self.assertNotIn("place.x", r.knowledge[0])
            self.assertEqual(r.pinned_ids, ["person.amy"])

    def test_linked_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "Amy")
            _add_kb(root, "place", "market", "The market")
            from lens.core.knowledge import KnowledgeStore
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("person.amy", ["place.market"])
            r = crawl_result_from_pins(root, ["person.amy+"], [])
            self.assertGreaterEqual(len(r.knowledge), 1)
            ids_found = [s for s in r.knowledge if "person.amy" in s or "place.market" in s]
            self.assertGreater(len(ids_found), 0)
            self.assertGreaterEqual(len(r.pinned_ids), 1)

    def test_linked_expansion_order_deterministic(self) -> None:
        """Knowledge from linked expansion follows ordered_ids: explicit first, then linked."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "Amy")
            _add_kb(root, "place", "market", "The market")
            from lens.core.knowledge import KnowledgeStore
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("person.amy", ["place.market"])
            r = crawl_result_from_pins(root, ["person.amy+"], [])
            self.assertEqual(len(r.knowledge), 2)
            self.assertIn("person.amy", r.knowledge[0])
            self.assertIn("place.market", r.knowledge[1])
            self.assertEqual(r.pinned_ids, ["person.amy", "place.market"])


class TestAssemblePromptKbEdit(unittest.TestCase):
    def test_new_item_includes_template_when_provided(self) -> None:
        result = CrawlResult.from_text_fields(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt_kb_edit(
            result,
            "Create a person",
            existing_content=None,
            template_content="Name:\nDescription:",
            include_template=False,
        )
        self.assertIn("RESULT TEMPLATE", msgs[1]["content"])
        self.assertIn("Name:", msgs[1]["content"])

    def test_existing_item_excludes_template_without_flag(self) -> None:
        result = CrawlResult.from_text_fields(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt_kb_edit(
            result,
            "Update the description",
            existing_content="Old content",
            template_content="Template here",
            include_template=False,
        )
        self.assertNotIn("RESULT TEMPLATE", msgs[1]["content"])
        self.assertIn("CURRENT TEXT", msgs[1]["content"])

    def test_existing_item_includes_template_with_flag(self) -> None:
        result = CrawlResult.from_text_fields(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt_kb_edit(
            result,
            "Edit",
            existing_content="Current",
            template_content="Template",
            include_template=True,
        )
        self.assertIn("RESULT TEMPLATE", msgs[1]["content"])
        self.assertIn("CURRENT TEXT", msgs[1]["content"])

    def test_crawl_sections_preserved(self) -> None:
        result = CrawlResult.from_text_fields(
            knowledge=["KB['x']\ndata"],
            previous_summaries=["Summary"],
            current_content="Passage",
        )
        msgs = assemble_prompt_kb_edit(result, "Edit", existing_content="Item")
        content = msgs[1]["content"]
        self.assertIn("RELEVANT KNOWLEDGE", content)
        self.assertIn("PREVIOUS EVENTS SUMMARY", content)
        self.assertIn("CURRENT PASSAGE", content)
        self.assertIn("Summary", content)
        self.assertIn("Passage", content)

    def test_current_kb_item_block_when_existing(self) -> None:
        result = CrawlResult.from_text_fields(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt_kb_edit(
            result,
            "Edit",
            existing_content="Existing KB content",
            template_content=None,
            include_template=False,
        )
        self.assertIn("CURRENT TEXT", msgs[1]["content"])
        self.assertIn("Existing KB content", msgs[1]["content"])

    def test_decodes_secrets_in_user_content(self) -> None:
        result = CrawlResult.from_text_fields(
            knowledge=["KB['x']\n<!-- ai:secret:\ngur frperg\n-->"],
            previous_summaries=[],
            current_content=None,
        )
        msgs = assemble_prompt_kb_edit(result, "Edit", existing_content="X")
        content = msgs[1]["content"]
        self.assertIn("the secret", content)
        self.assertNotIn("gur frperg", content)


# ---------------------------------------------------------------------------
# spine_path
# ---------------------------------------------------------------------------


class TestSpinePath(unittest.TestCase):
    def _nr(self, tmp: Path) -> Path:
        """Return narrative root for a test project."""
        return tmp / "narrative" / "test"

    def test_same_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nr = self._nr(Path(tmp))
            nr.mkdir(parents=True)
            node = NarrativeNode(narrative_root=nr, key_path=("ch1",))
            path = spine_path(node, node)
            self.assertEqual(len(path), 1)
            self.assertEqual(path[0].key_path, ("ch1",))

    def test_ancestor_to_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nr = self._nr(Path(tmp))
            nr.mkdir(parents=True)
            ancestor = NarrativeNode(narrative_root=nr, key_path=())
            descendant = NarrativeNode(narrative_root=nr, key_path=("ch1", "sc1"))
            path = spine_path(ancestor, descendant)
            key_paths = [n.key_path for n in path]
            self.assertEqual(key_paths, [(), ("ch1",), ("ch1", "sc1")])

    def test_across_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nr = self._nr(Path(tmp))
            nr.mkdir(parents=True)
            left = NarrativeNode(narrative_root=nr, key_path=("ch1", "sc1"))
            right = NarrativeNode(narrative_root=nr, key_path=("ch1", "sc2"))
            path = spine_path(left, right)
            key_paths = [n.key_path for n in path]
            # left → parent ch1 → right
            self.assertEqual(key_paths, [("ch1", "sc1"), ("ch1",), ("ch1", "sc2")])

    def test_deep_cross_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nr = self._nr(Path(tmp))
            nr.mkdir(parents=True)
            left = NarrativeNode(narrative_root=nr, key_path=("ch1",))
            right = NarrativeNode(narrative_root=nr, key_path=("ch2", "sc1"))
            path = spine_path(left, right)
            key_paths = [n.key_path for n in path]
            # ch1 → root → ch2 → ch2/sc1
            self.assertEqual(key_paths, [("ch1",), (), ("ch2",), ("ch2", "sc1")])


# ---------------------------------------------------------------------------
# crawl with anchor (narrative slice)
# ---------------------------------------------------------------------------


class TestCrawlWithAnchor(unittest.TestCase):
    def test_anchor_none_is_standard_crawl(self) -> None:
        """anchor=None produces identical results to the existing behavior."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _root, narrative = _make_project(d)
            result_default = crawl(narrative)
            result_explicit = crawl(narrative, anchor=None)
            self.assertEqual(result_default.previous_summaries, result_explicit.previous_summaries)
            self.assertEqual(result_default.current_content, result_explicit.current_content)

    def test_anchor_on_same_node_only_text_after_anchor_line(self) -> None:
        """When anchor is on the cursor's own ancestor, only text after the anchor line is collected."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _root, narrative = _make_project(d)
            # Write multiline content to root
            root_md = narrative.md_path()
            root_md.write_text("Line one BEFORE anchor\nLine two BEFORE anchor\nLine three AFTER anchor\nLine four AFTER anchor\n")
            # Anchor at line 3 means text from line 3 onward
            anchor = SliceAnchor(node=narrative, line_end=3)
            # Crawl at the same node (root)
            result = crawl(narrative, anchor=anchor)
            # Root is both anchor and cursor → current_content
            self.assertIsNotNone(result.current_content)
            self.assertNotIn("BEFORE anchor", result.current_content or "")
            self.assertIn("AFTER anchor", result.current_content or "")

    def test_anchor_on_ancestor_spine_to_cursor(self) -> None:
        """Anchor on root, cursor deeper — collects spine text, not just ancestors."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _root, narrative = _make_project(d)
            root_md = narrative.md_path()
            root_md.write_text(
                "Root line 1 BEFORE\n"
                "Root line 2 BEFORE\n"
                "Root line 3 AFTER\n"
                "[section:ch1]: #\n"
            )
            # Create child ch1
            ch1_dir = narrative.narrative_root / "ch1"
            ch1_dir.mkdir()
            (ch1_dir / "_node.md").write_text("Chapter 1 content\n")

            child = NarrativeNode(narrative_root=narrative.narrative_root, key_path=("ch1",))
            anchor = SliceAnchor(node=narrative, line_end=3)
            result = crawl(child, anchor=anchor)

            # Root text after anchor → previous_summaries
            self.assertTrue(len(result.previous_summaries) >= 1)
            combined_prev = "\n".join(result.previous_summaries)
            self.assertNotIn("BEFORE", combined_prev)
            self.assertIn("AFTER", combined_prev)
            # Child text → current_content
            self.assertIn("Chapter 1", result.current_content or "")

    def test_kb_resolution_unaffected_by_anchor(self) -> None:
        """KB pins still resolve from full ancestor chain even with an anchor."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _init_repo(d)
            _root, narrative = _make_project(d)
            # Add a KB object
            _add_kb(d, "person", "alice", "Alice the adventurer")
            # Pin it in root front matter
            root_md = narrative.md_path()
            root_md.write_text("[\n  kb_pin:\n    - person.alice\n]: #\n\nRoot narrative\n")
            subprocess.run(["git", "add", "-A"], cwd=d, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "pin"], cwd=d, capture_output=True, check=True)

            # Anchor at line 2 (after front matter) on root
            anchor = SliceAnchor(node=narrative, line_end=2)
            result = crawl(narrative, anchor=anchor)
            # KB should still be resolved
            self.assertIn("person.alice", result.pinned_ids)


class TestAssembledKbSecretsAreModelForm(unittest.TestCase):
    """The KB block a model is shown must be decoded — see issue #74.

    ``crawl`` decodes the graph, then ``assemble_prompt`` re-runs the default
    transforms over the render-time components it adds. Because the decode is
    ROT13 — an involution — a second pass over the KB components used to hand
    the model ciphertext. Models copy that back verbatim into a ``kb`` block,
    persist encodes it once more, and the plaintext lands on disk.
    """

    def _project_with_secret(self, tmp: Path) -> NarrativeNode:
        root, node = _make_project(_init_repo(tmp))
        _add_kb(
            root,
            "front",
            "blight",
            "# The Spreading Blight\n\n"
            "- Problem: a grey rot\n\n"
            "<!-- ai:secret:\ngur oyvtug vf zntvpny\n-->\n",
        )
        root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
        root_node.md_path().write_text(
            "[\n  kb_pin:\n    - front.blight\n]: #\n\n# test\n"
        )
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "pin"], cwd=root, capture_output=True, check=True
        )
        from lens.core.knowledge import KnowledgeStore
        from lens.core.media import MediaService

        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        return node

    def test_relevant_knowledge_block_is_decoded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            node = self._project_with_secret(Path(tmp))
            result = crawl(node)
            messages = assemble_prompt(
                result, system_prompt="sys", instruction="advance a day"
            )

        user = messages[1]["content"]
        self.assertIn("the blight is magical", user)
        self.assertNotIn("gur oyvtug vf zntvpny", user)

    def test_decoded_once_even_when_assembled_twice(self) -> None:
        """Retry/regeneration re-assembles from the same CrawlResult."""
        with tempfile.TemporaryDirectory() as tmp:
            node = self._project_with_secret(Path(tmp))
            result = crawl(node)
            assemble_prompt(result, system_prompt="sys", instruction="first")
            messages = assemble_prompt(result, system_prompt="sys", instruction="again")

        self.assertIn("the blight is magical", messages[1]["content"])


class TestCurrentPassageOverride(unittest.TestCase):
    """An override replaces the passage, so nothing may be derived from the node.

    `edit` / `collate` pass a slice of prose as the passage.  Deriving mentions
    from the node's full text instead would inject a `state` object into
    [LIVE STATE], and render effects claiming expansions, describing text the
    prompt does not contain.
    """

    def _project(self, tmp: str):
        root, node = _make_project(_init_repo(Path(tmp)))
        _add_kb(root, "tracker", "combat", "Goblin HP 7/7")
        _add_kb(root, "spell", "aid", "Aid raises hit point maximums.")
        from lens.core.knowledge import KnowledgeStore
        from lens.core.media import MediaService

        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        KnowledgeStore.for_project(root).add_tags("tracker.combat", ["state"])
        root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
        root_node.md_path().write_text(
            "# test\n\nKira waits.\n\n"
            "[mention: tracker.combat]: #\n\n[mention: spell.aid]: #\n"
        )
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "mentions"], cwd=root, capture_output=True, check=True
        )
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        return node

    def test_override_suppresses_state_and_effects_from_the_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            node = self._project(tmp)

            result = crawl(
                CrawlSpec.of(node, current_passage_override="Earlier prose only.")
            )

            self.assertEqual(result.state_pins, [])
            self.assertEqual(
                [e for e in result.render_effects if e.kind.startswith("kb-")], []
            )
            self.assertNotIn("KB['spell.aid']", result.current_content or "")

    def test_override_still_expands_a_mention_it_contains(self) -> None:
        """`explain --line` hands crawl a raw truncation and must get the pins."""
        with tempfile.TemporaryDirectory() as tmp:
            node = self._project(tmp)

            result = crawl(
                CrawlSpec.of(
                    node,
                    current_passage_override="Kira waits.\n\n[mention: spell.aid]: #\n",
                )
            )

            self.assertIn("KB['spell.aid']", result.current_content or "")
            self.assertNotIn("[mention:", result.current_content or "")

    def test_override_respects_pin_suppression(self) -> None:
        """An already-pinned object must not be expanded a second time."""
        with tempfile.TemporaryDirectory() as tmp:
            node = self._project(tmp)

            result = crawl(
                CrawlSpec.of(
                    node,
                    extra_pins=["spell.aid"],
                    current_passage_override="Kira waits.\n\n[mention: spell.aid]: #\n",
                )
            )

            self.assertIn("spell.aid", result.pinned_ids)
            self.assertNotIn("KB['spell.aid']", result.current_content or "")


class TestStateTagTailRender(unittest.TestCase):
    """`state`-tagged KB objects render at the tail, not in RELEVANT KNOWLEDGE."""

    def _project_with_state_pin(
        self, tmp: Path, *, extra_pins: str = ""
    ) -> NarrativeNode:
        root, node = _make_project(_init_repo(tmp))
        _add_kb(root, "lore", "world", "The world is old.")
        _add_kb(root, "tracker", "combat", "Goblin HP 7/7")
        from lens.core.knowledge import KnowledgeStore
        from lens.core.media import MediaService

        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        kb = KnowledgeStore.for_project(root)
        kb.add_tags("tracker.combat", ["state"])
        root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
        root_node.md_path().write_text(
            "[\n  kb_pin:\n    - lore.world\n    - tracker.combat\n"
            + extra_pins
            + "]: #\n\n# test\n"
        )
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "pin"], cwd=root, capture_output=True, check=True
        )
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        return node

    def test_state_object_leaves_relevant_knowledge_and_precedes_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            node = self._project_with_state_pin(Path(tmp))
            result = crawl(node)
            messages = assemble_prompt(
                result, system_prompt="sys", instruction="continue"
            )

        user = messages[1]["content"]
        knowledge_block = user.split("--- end RELEVANT KNOWLEDGE ---")[0]
        self.assertIn("lore.world", knowledge_block)
        self.assertNotIn("tracker.combat", knowledge_block)

        self.assertIn("Goblin HP 7/7", user)
        state_at = user.index("--- begin LIVE STATE ---")
        task_at = user.index("--- begin TASK ---")
        self.assertLess(state_at, task_at)
        # Nothing between the state block and the task block.
        between = user[user.index("--- end LIVE STATE ---") : task_at]
        self.assertEqual(between.replace("--- end LIVE STATE ---", "").strip(), "")

    def test_state_object_still_counts_as_pinned(self) -> None:
        """The divert is a render decision; pin resolution is unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            node = self._project_with_state_pin(Path(tmp))
            result = crawl(node)
            assemble_prompt(result, system_prompt="sys", instruction="continue")

        self.assertEqual(result.pinned_ids, ["lore.world", "tracker.combat"])
        self.assertEqual(len(result.knowledge), 2)

    def test_untagged_project_renders_no_state_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "lore", "world", "The world is old.")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "[\n  kb_pin:\n    - lore.world\n]: #\n\n# test\n"
            )
            subprocess.run(
                ["git", "add", "-A"], cwd=root, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "pin"], cwd=root, capture_output=True, check=True
            )
            from lens.core.knowledge import KnowledgeStore
            from lens.core.media import MediaService

            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            result = crawl(node)
            messages = assemble_prompt(
                result, system_prompt="sys", instruction="continue"
            )

        self.assertNotIn("LIVE STATE", messages[1]["content"])

    def test_state_block_lands_after_last_turn_in_multi_turn_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            node = self._project_with_state_pin(Path(tmp))
            result = crawl(node)
            messages = assemble_prompt(
                result,
                system_prompt="sys",
                instruction="continue",
                turns=[
                    ("user", "Kira swings."),
                    ("assistant", "The goblin parries."),
                ],
            )

        # State must not ride in the cacheable prefix with the knowledge block.
        prefix = messages[1]["content"]
        self.assertIn("lore.world", prefix)
        self.assertNotIn("Goblin HP 7/7", prefix)

        tail = messages[-1]["content"]
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("Goblin HP 7/7", tail)
        self.assertLess(tail.index("--- begin LIVE STATE ---"), tail.index("--- begin TASK ---"))
        self.assertEqual(messages[-2]["content"], "The goblin parries.")

    def test_mentioned_state_object_also_diverts(self) -> None:
        """A state object entering scope via a mention lands at the tail too.

        Mentions normally expand in place, but a `state` object must not: its
        content changes between beats, and inlining it would freeze a snapshot
        into the append-only transcript.  It is diverted to [LIVE STATE] like
        any other state object instead.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "tracker", "combat", "Goblin HP 7/7")
            from lens.core.knowledge import KnowledgeStore
            from lens.core.media import MediaService

            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            KnowledgeStore.for_project(root).add_tags("tracker.combat", ["state"])
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            root_node.md_path().write_text(
                "# test\n\nKira checks the tracker now.\n[mention: tracker.combat]: #\n"
            )
            subprocess.run(
                ["git", "add", "-A"], cwd=root, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "prose"], cwd=root, capture_output=True, check=True
            )
            KnowledgeStore.clear_registry()
            MediaService.clear_registry()
            result = crawl(node)
            messages = assemble_prompt(
                result, system_prompt="sys", instruction="continue"
            )

        user = messages[1]["content"]
        self.assertIn("--- begin LIVE STATE ---", user)
        self.assertNotIn("RELEVANT KNOWLEDGE", user)
        self.assertLess(
            user.index("--- begin LIVE STATE ---"), user.index("--- begin TASK ---")
        )
