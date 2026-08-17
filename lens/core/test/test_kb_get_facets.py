"""Unit tests for ``kb_get(facets=True)`` — the ``--facet-expand`` surface.

Facet expansion applies to the ids the caller asked for, never to ids reached
through ``+`` link expansion.  That is the same root-pins-only rule the crawl
uses, and it is what keeps the unrelated dash collisions in the shipped
datasets (``stat.guard`` / ``stat.guard-captain``) out of the result.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lens.core.commands.kb import kb_get
from lens.core.knowledge import KnowledgeStore


def _make_project(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / "lens.toml").write_text("[project]\n")
    (tmp / "knowledge").mkdir()
    (tmp / "knowledge" / "tags.toml").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True
    )


class TestKbGetFacets(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        self.store = KnowledgeStore(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get(self, ids: list[str], *, facets: bool) -> list[str]:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            ordered, _objects = kb_get(ids, facets=facets)
        return ordered

    def test_off_by_default(self) -> None:
        self.store.store_object("front.problem", "The problem.")
        self.store.store_object("front.problem-prep", "Prep notes.")
        self.assertEqual(self._get(["front.problem"], facets=False), ["front.problem"])

    def test_facet_follows_its_parent(self) -> None:
        self.store.store_object("front.problem", "The problem.")
        self.store.store_object("front.problem-prep", "Prep notes.")
        self.assertEqual(
            self._get(["front.problem"], facets=True),
            ["front.problem", "front.problem-prep"],
        )

    def test_objects_dict_carries_the_facet(self) -> None:
        self.store.store_object("front.problem", "The problem.")
        self.store.store_object("front.problem-prep", "Prep notes.")
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            _ordered, objects = kb_get(["front.problem"], facets=True)
        self.assertIn("front.problem-prep", objects)
        self.assertIn("Prep notes.", objects["front.problem-prep"].text)

    def test_multiple_facets_sorted_after_their_parent(self) -> None:
        self.store.store_object("pc.amy", "Amy.")
        self.store.store_object("pc.amy-secrets", "Secrets.")
        self.store.store_object("pc.amy-background", "Background.")
        self.assertEqual(
            self._get(["pc.amy"], facets=True),
            ["pc.amy", "pc.amy-background", "pc.amy-secrets"],
        )

    def test_each_requested_root_gets_its_own_facets(self) -> None:
        self.store.store_object("front.a", "A.")
        self.store.store_object("front.a-prep", "A prep.")
        self.store.store_object("front.b", "B.")
        self.store.store_object("front.b-prep", "B prep.")
        self.assertEqual(
            self._get(["front.a", "front.b"], facets=True),
            ["front.a", "front.a-prep", "front.b", "front.b-prep"],
        )

    def test_linked_object_does_not_gain_facets(self) -> None:
        """The collision case: `stat.guard` reached via `+` must not pull the captain."""
        self.store.store_object("party.roster", "The roster.")
        self.store.store_object("stat.guard", "A guard.")
        self.store.store_object("stat.guard-captain", "An unrelated stat block.")
        self.store.add_tags("party.roster", ["stat.guard"])
        ordered = self._get(["party.roster+"], facets=True)
        self.assertIn("stat.guard", ordered)
        self.assertNotIn("stat.guard-captain", ordered)

    def test_requested_root_with_plus_gets_both(self) -> None:
        self.store.store_object("front.problem", "The problem.")
        self.store.store_object("front.problem-prep", "Prep notes.")
        self.store.store_object("person.villain", "The villain.")
        self.store.add_tags("front.problem", ["person.villain"])
        ordered = self._get(["front.problem+"], facets=True)
        self.assertEqual(
            sorted(ordered),
            ["front.problem", "front.problem-prep", "person.villain"],
        )

    def test_multi_level_facet_arrives(self) -> None:
        self.store.store_object("front.problem", "The problem.")
        self.store.store_object("front.problem-prep-notes", "Deep prep.")
        self.assertEqual(
            self._get(["front.problem"], facets=True),
            ["front.problem", "front.problem-prep-notes"],
        )

    def test_object_without_facets_is_unchanged(self) -> None:
        self.store.store_object("front.lonely", "No facets here.")
        self.assertEqual(self._get(["front.lonely"], facets=True), ["front.lonely"])

    def test_facet_requested_directly_is_not_duplicated(self) -> None:
        self.store.store_object("front.problem", "The problem.")
        self.store.store_object("front.problem-prep", "Prep notes.")
        self.assertEqual(
            self._get(["front.problem", "front.problem-prep"], facets=True),
            ["front.problem", "front.problem-prep"],
        )

    def test_facets_of_a_missing_parent_are_still_returned(self) -> None:
        """`list_facet_ids` does not require the parent to exist, and neither
        should asking for it: the question "what prep is there for X" is fair
        even when X itself was never written."""
        self.store.store_object("front.ghost-prep", "Prep with no parent.")
        self.assertEqual(self._get(["front.ghost"], facets=True), ["front.ghost-prep"])
