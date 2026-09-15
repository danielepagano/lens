"""Tests for ``lens spine`` — the narrative spine, root to cursor."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.spine import (
    ROLE_CURRENT,
    ROLE_SUMMARY,
    spine_report,
)
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
from lens.testing.project import setup_test_project

ROOT_PROSE = "The kingdom had been at peace for a hundred years."
CHAPTER_PROSE = "Amy reached the dungeon gate at dusk and found it already open."
SCENE_PROSE = "The hinges had been cut, not forced. Someone wanted her to walk in."


def _write(node: NarrativeNode, text: str) -> None:
    """Write *text* as a folder node, creating the directory if needed.

    ``md_path()`` raises for a node that does not exist yet, so the path is
    built here; every node in these fixtures is a folder node so the spine is
    the same shape whether or not a node has children.
    """
    path = node.narrative_root.joinpath(*node.key_path) / "_node.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _node(session: ProjectSession, *keys: str) -> NarrativeNode:
    narrative = session.active_narrative
    assert narrative is not None
    return NarrativeNode(narrative_root=narrative.narrative_root, key_path=keys)


class SpineTestCase(unittest.TestCase):
    """A three-level spine: root → chapter-1 → scene-2, cursor at the leaf."""

    session: ProjectSession
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        cls.tmp = tempfile.mkdtemp(prefix="lens_spine_")
        cls.session = setup_test_project(
            Path(cls.tmp), "http://127.0.0.1:1/v1", opening_write=False
        )
        root = _node(cls.session)
        _write(
            root,
            "[\n    kb_pin:\n    - person.amy\n]: #\n\n"
            f"{ROOT_PROSE}\n\n[section:chapter-1]: #\n",
        )
        _write(
            _node(cls.session, "chapter-1"),
            f"{CHAPTER_PROSE}\n\n[section:scene-2]: #\n",
        )
        _write(
            _node(cls.session, "chapter-1", "scene-2"),
            f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n[/write]: #\n",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()


class TestSpineShape(SpineTestCase):
    def test_walks_from_the_root_to_the_cursor(self) -> None:
        report = spine_report(self.session)
        self.assertEqual(
            [n.address for n in report.nodes],
            ["story", "story/chapter-1", "story/chapter-1/scene-2"],
        )
        self.assertEqual([n.depth for n in report.nodes], [0, 1, 2])
        self.assertEqual(report.address, "story/chapter-1/scene-2")
        self.assertEqual(report.narrative, "story")

    def test_only_the_cursor_node_is_the_current_passage(self) -> None:
        report = spine_report(self.session)
        roles = [n.role for n in report.nodes]
        self.assertEqual(roles, [ROLE_SUMMARY, ROLE_SUMMARY, ROLE_CURRENT])

    def test_each_node_carries_its_own_prose(self) -> None:
        report = spine_report(self.session)
        self.assertIn(ROOT_PROSE, report.nodes[0].text)
        self.assertEqual(report.nodes[1].text, CHAPTER_PROSE)
        self.assertEqual(report.nodes[2].text, SCENE_PROSE)

    def test_annotations_are_stripped_from_the_reported_prose(self) -> None:
        report = spine_report(self.session)
        for node in report.nodes:
            self.assertNotIn("]: #", node.text)
            self.assertNotIn("kb_pin", node.text)

    def test_text_joins_the_spine_in_order(self) -> None:
        report = spine_report(self.session)
        text = report.text
        self.assertLess(text.index(ROOT_PROSE), text.index(CHAPTER_PROSE))
        self.assertLess(text.index(CHAPTER_PROSE), text.index(SCENE_PROSE))

    def test_reports_the_operator_that_would_run_at_the_cursor(self) -> None:
        report = spine_report(self.session)
        self.assertEqual(report.operator, "write")
        self.assertIsNone(report.open_session)

    def test_totals_sum_the_reported_nodes(self) -> None:
        report = spine_report(self.session)
        self.assertEqual(report.total_bytes, sum(n.bytes for n in report.nodes))
        self.assertEqual(report.total_tokens, sum(n.tokens for n in report.nodes))
        self.assertEqual(len(report.contributing), 3)
        for node in report.nodes:
            self.assertEqual(node.bytes, len(node.text.encode("utf-8")))
            self.assertGreater(node.tokens, 0)


class TestSpineAtAnAddress(SpineTestCase):
    def test_an_explicit_address_shortens_the_spine(self) -> None:
        report = spine_report(self.session, address="/chapter-1")
        self.assertEqual(
            [n.address for n in report.nodes], ["story", "story/chapter-1"]
        )
        self.assertEqual(report.nodes[-1].role, ROLE_CURRENT)
        self.assertEqual(report.nodes[-1].text, CHAPTER_PROSE)

    def test_the_root_address_is_a_spine_of_one(self) -> None:
        report = spine_report(self.session, address="/")
        self.assertEqual([n.address for n in report.nodes], ["story"])
        self.assertEqual(report.nodes[0].role, ROLE_CURRENT)

    def test_an_unknown_address_is_an_error(self) -> None:
        with self.assertRaises(LensException):
            spine_report(self.session, address="/chapter-9")

    def test_a_line_truncates_the_cursor_passage_only(self) -> None:
        later = "She never found out who had cut them."
        _write(
            _node(self.session, "chapter-1", "scene-2"),
            f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n"
            f"{later}\n\n[/write]: #\n",
        )
        try:
            full = spine_report(self.session)
            self.assertIn(later, full.nodes[-1].text)

            # Line 5 is SCENE_PROSE; `later` is two lines below it.
            cut = spine_report(self.session, address="/chapter-1/scene-2", line=5)
            self.assertEqual(cut.line, 5)
            self.assertTrue(cut.nodes[-1].truncated)
            self.assertIn(SCENE_PROSE, cut.nodes[-1].text)
            self.assertNotIn(later, cut.nodes[-1].text)
            self.assertLess(cut.total_bytes, full.total_bytes)

            # Ancestors are untouched by the cut.
            self.assertEqual(cut.nodes[1].text, full.nodes[1].text)
            self.assertFalse(cut.nodes[1].truncated)
        finally:
            _write(
                _node(self.session, "chapter-1", "scene-2"),
                f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n[/write]: #\n",
            )

    def test_a_line_suffix_on_the_address_is_equivalent(self) -> None:
        suffixed = spine_report(self.session, address="/chapter-1/scene-2@3")
        explicit = spine_report(self.session, address="/chapter-1/scene-2", line=3)
        self.assertEqual(suffixed.to_dict(), explicit.to_dict())

    def test_a_line_out_of_range_is_an_error(self) -> None:
        with self.assertRaises(LensException):
            spine_report(self.session, address="/chapter-1/scene-2", line=9999)


class TestSpineEmptyNodes(SpineTestCase):
    def test_a_node_with_only_annotations_is_listed_but_contributes_nothing(
        self,
    ) -> None:
        _write(
            _node(self.session, "chapter-1", "scene-2"),
            "[write\n    prompt: go on\n]: #\n[/write]: #\n",
        )
        try:
            report = spine_report(self.session)
            leaf = report.nodes[-1]
            self.assertEqual(leaf.address, "story/chapter-1/scene-2")
            self.assertFalse(leaf.contributes)
            self.assertEqual(leaf.text, "")
            self.assertEqual(leaf.bytes, 0)
            self.assertTrue(leaf.has_file)
            # The spine is still three nodes long; one of them is just silent.
            self.assertEqual(len(report.nodes), 3)
            self.assertEqual(len(report.contributing), 2)
        finally:
            _write(
                _node(self.session, "chapter-1", "scene-2"),
                f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n[/write]: #\n",
            )


class TestSpineScopeExpansion(SpineTestCase):
    """The spine must render mentions exactly as the prompt does, or it lies."""

    def test_an_include_expands_in_place_in_the_cursor_passage(self) -> None:
        _write(
            _node(self.session, "chapter-1", "scene-2"),
            f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n"
            "[include:person.hero]: #\n\n[/write]: #\n",
        )
        try:
            report = spine_report(self.session)
            self.assertIn("person.hero", report.nodes[-1].text)
        finally:
            _write(
                _node(self.session, "chapter-1", "scene-2"),
                f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n[/write]: #\n",
            )

    def test_an_include_of_an_already_pinned_object_is_suppressed(self) -> None:
        # person.amy is pinned at the root, so the prompt does not expand it a
        # second time — and neither may the spine.
        _write(
            _node(self.session, "chapter-1", "scene-2"),
            f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n"
            "[include:person.amy]: #\n\n[/write]: #\n",
        )
        try:
            report = spine_report(self.session)
            self.assertNotIn("brave protagonist", report.nodes[-1].text)
        finally:
            _write(
                _node(self.session, "chapter-1", "scene-2"),
                f"[write\n    prompt: go on\n]: #\n\n{SCENE_PROSE}\n\n[/write]: #\n",
            )


class TestSpineReportSerialization(SpineTestCase):
    def test_to_dict_round_trips_the_spine_and_its_totals(self) -> None:
        report = spine_report(self.session)
        data = report.to_dict()
        self.assertEqual(data["address"], "story/chapter-1/scene-2")
        self.assertEqual(data["operator"], "write")
        self.assertEqual(len(data["nodes"]), 3)
        self.assertEqual(data["totals"]["nodes"], 3)
        self.assertEqual(data["totals"]["contributing_nodes"], 3)
        self.assertEqual(data["totals"]["bytes"], report.total_bytes)
        self.assertEqual(data["nodes"][0]["role"], ROLE_SUMMARY)
        self.assertEqual(data["nodes"][-1]["role"], ROLE_CURRENT)

    def test_chars_per_token_scales_the_estimate(self) -> None:
        coarse = spine_report(self.session, chars_per_token=8)
        fine = spine_report(self.session, chars_per_token=2)
        self.assertEqual(coarse.total_bytes, fine.total_bytes)
        self.assertLess(coarse.total_tokens, fine.total_tokens)

    def test_a_zero_divisor_is_rejected(self) -> None:
        with self.assertRaises(LensException):
            spine_report(self.session, chars_per_token=0)


if __name__ == "__main__":
    unittest.main()
