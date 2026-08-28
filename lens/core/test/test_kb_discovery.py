"""Finding things in the merged knowledge store: ``kb search``, ``list``, ``refs``.

The premise these pin down is that a checkout is not the store. Datasets resolve
outside the repository, precedence between them is a computation, and the tag
index and the ``+`` / facet / ``rules.<type>`` relationships are not recoverable
from the text on disk. So every case here is one a ``grep -r`` over the project
tree would get wrong: a dataset body it cannot see, a shadowed copy it would
report twice, a pin that reaches an object without ever naming it.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.commands.kb_refs import Ref, RefsResult, kb_refs, refs_payload
from lens.core.commands.kb_search import (
    SearchResult,
    format_hit_lines,
    format_match_line,
    kb_list,
    kb_search,
    list_payload,
    search_payload,
)
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore
from lens.core.module_requests import clear_module_registry


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


class _ProjectCase(unittest.TestCase):
    """A project with the bundled ``testing`` dataset behind it.

    ``testing`` ships ``person.hero``, ``person.villain``, ``rules.skirmish``
    (registered as a ``play`` module in its manifest) and ``rules.system`` —
    enough for shadowing, module registration and dataset-only reach to have
    real witnesses instead of hand-built stand-ins.
    """

    datasets = ["testing"]

    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        clear_module_registry()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()
        _git(self.root, "init")
        _git(self.root, "config", "user.email", "test@test.com")
        _git(self.root, "config", "user.name", "Test")
        listed = ", ".join(f'"{name}"' for name in self.datasets)
        (self.root / "lens.toml").write_text(
            f'[project]\nnarrative = "story"\ndatasets = [{listed}]\n',
            encoding="utf-8",
        )
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge" / "tags.toml").write_text("", encoding="utf-8")
        self.narrative_dir = self.root / "narrative" / "story"
        self.narrative_dir.mkdir(parents=True)
        (self.narrative_dir / "_node.md").write_text("Kira waits.\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-m", "init")
        self.store = KnowledgeStore.for_project(self.root)

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        clear_module_registry()
        self._tmp.cleanup()

    def write_node(self, text: str, *, key: str | None = None) -> Path:
        path = (
            self.narrative_dir / f"{key}.md"
            if key
            else self.narrative_dir / "_node.md"
        )
        path.write_text(text, encoding="utf-8")
        return path

    def search(self, pattern: str, **kwargs: Any) -> SearchResult:
        return kb_search(pattern, store=self.store, **kwargs)

    def refs(self, canonical_id: str, **kwargs: Any) -> RefsResult:
        return kb_refs(
            canonical_id, store=self.store, project_root=self.root, **kwargs
        )


class TestSearchFindsWhatGrepCannot(_ProjectCase):
    def test_it_reaches_bodies_that_live_outside_the_checkout(self) -> None:
        """The whole reason the command exists: datasets are not in the repo."""
        result = self.search("skirmish", ignore_case=True)

        self.assertIn("rules.skirmish", [hit.id for hit in result.hits])

    def test_a_shadowed_object_is_searched_once_from_the_winning_store(self) -> None:
        self.store.store_object("person.hero", "A hero who grapples.\n")

        result = self.search("grapples")

        self.assertEqual([hit.id for hit in result.hits], ["person.hero"])
        hit = result.hits[0]
        self.assertEqual(hit.source.kind, "project")
        self.assertEqual(hit.source.shadows, ("testing",))

    def test_the_shadowed_copys_text_is_not_searched(self) -> None:
        """Grepping three trees finds the loser too; resolving does not."""
        dataset_text = (
            self.store.get_objects(["person.hero"])["person.hero"].text
        )
        distinctive = dataset_text.split("\n")[0]
        self.store.store_object("person.hero", "Nothing in common.\n")

        result = self.search(distinctive, fixed_string=True)

        self.assertEqual([hit.id for hit in result.hits], [])


class TestSearchMatching(_ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.store_object(
            "person.rowan",
            "ROWAN\nA ranger.\n\nShe grapples the guard.\nShe grapples again.\n",
        )
        self.store.add_tags("person.rowan", ["pc", "place.tavern"])

    def test_a_body_match_reports_its_line_and_the_line_text(self) -> None:
        result = self.search("grapples the guard")

        match = result.hits[0].matches[0]
        self.assertEqual(match.field, "body")
        self.assertEqual(match.line, 4)
        self.assertEqual(match.text, "She grapples the guard.")

    def test_matches_come_back_in_line_order(self) -> None:
        result = self.search("grapples")

        self.assertEqual([m.line for m in result.hits[0].matches], [4, 5])

    def test_hits_come_back_in_id_order_with_no_ranking(self) -> None:
        self.store.store_object("person.aaron", "A guard.\n")
        self.store.store_object("person.zeb", "A guard.\n")

        result = self.search("A guard")

        ids = [hit.id for hit in result.hits]
        self.assertEqual(ids, sorted(ids))

    def test_an_id_match_reports_line_zero_and_names_the_field(self) -> None:
        result = self.search("rowan")

        match = result.hits[0].matches[0]
        self.assertEqual((match.field, match.line, match.text), ("id", 0, "person.rowan"))

    def test_a_type_match_is_suppressed_when_the_id_already_matched(self) -> None:
        """`kb search person` should not report the same news twice per object."""
        result = self.search("person")

        fields = [m.field for m in result.hits[0].matches]
        self.assertIn("id", fields)
        self.assertNotIn("type", fields)

    def test_a_type_matches_on_its_own_when_the_id_does_not(self) -> None:
        result = self.search("^person$")

        hit = next(h for h in result.hits if h.id == "person.rowan")
        self.assertEqual([m.field for m in hit.matches], ["type"])

    def test_a_tag_matches(self) -> None:
        result = self.search("^pc$")

        hit = next(h for h in result.hits if h.id == "person.rowan")
        self.assertEqual([(m.field, m.text) for m in hit.matches], [("tag", "pc")])

    def test_ignore_case(self) -> None:
        self.assertEqual(self.search("ROWAN, a ranger").hits, [])
        self.assertEqual(
            [h.id for h in self.search("A RANGER", ignore_case=True).hits],
            ["person.rowan"],
        )

    def test_a_fixed_string_is_not_a_regex(self) -> None:
        self.store.store_object("person.dot", "Cost: 1.5 gold\n")

        loose = self.search(r"1.5", type_filter="person")
        literal = self.search("1.5", fixed_string=True, type_filter="person")

        self.assertEqual([h.id for h in loose.hits], ["person.dot"])
        self.assertEqual([h.id for h in literal.hits], ["person.dot"])
        self.assertEqual(self.search("1x5", fixed_string=True).hits, [])

    def test_word_mode_matches_whole_words_only(self) -> None:
        self.store.store_object("person.guardian", "A guardian.\n")

        loose = [h.id for h in self.search("guard", type_filter="person").hits]
        worded = [
            h.id for h in self.search("guard", word=True, type_filter="person").hits
        ]

        self.assertIn("person.guardian", loose)
        self.assertNotIn("person.guardian", worded)
        self.assertIn("person.rowan", worded)

    def test_context_lines_come_back_with_each_body_match(self) -> None:
        result = self.search("grapples the guard", context=1)

        match = result.hits[0].matches[0]
        self.assertEqual(match.context_before, [(3, "")])
        self.assertEqual(match.context_after, [(5, "She grapples again.")])

    def test_context_never_repeats_a_line_that_is_itself_a_match(self) -> None:
        result = self.search("grapples", context=2)

        first, second = result.hits[0].matches
        self.assertNotIn(5, [n for n, _ in first.context_after])
        self.assertNotIn(4, [n for n, _ in second.context_before])

    def test_an_invalid_pattern_is_a_lens_error_not_a_traceback(self) -> None:
        with self.assertRaises(LensException):
            self.search("[unclosed")

    def test_an_empty_pattern_is_refused(self) -> None:
        with self.assertRaises(LensException):
            self.search("")


class TestSearchFilters(_ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.store_object("person.rowan", "ROWAN\nA ranger of the front.\n")
        self.store.store_object("place.front", "FRONT\nThe front line.\n")
        self.store.add_tags("person.rowan", ["pc"])

    def test_the_type_filter_narrows_to_one_type(self) -> None:
        result = self.search("front", type_filter="place")

        self.assertEqual([h.id for h in result.hits], ["place.front"])

    def test_the_tag_filter_narrows_to_tagged_objects(self) -> None:
        result = self.search("front", tags=["pc"])

        self.assertEqual([h.id for h in result.hits], ["person.rowan"])

    def test_a_bare_type_works_as_a_tag_filter(self) -> None:
        """Type-as-tag holds here too, or the filter would lie by omission."""
        result = self.search("front", tags=["place"])

        self.assertEqual([h.id for h in result.hits], ["place.front"])

    def test_repeated_tags_are_anded(self) -> None:
        self.assertEqual(self.search("front", tags=["pc", "place"]).hits, [])

    def test_the_source_filter_keeps_only_project_objects(self) -> None:
        result = self.search("the", ignore_case=True, source="project")

        self.assertTrue(result.hits)
        self.assertTrue(all(h.source.kind == "project" for h in result.hits))

    def test_the_source_filter_keeps_only_dataset_objects(self) -> None:
        result = self.search("the", ignore_case=True, source="dataset")

        self.assertTrue(result.hits)
        self.assertTrue(all(h.source.kind == "dataset" for h in result.hits))

    def test_templates_are_excluded_unless_asked_for(self) -> None:
        without = [h.id for h in self.search("_template").hits]
        self.assertNotIn("person._template", without)

        with_templates = [
            h.id for h in self.search("_template", include_templates=True).hits
        ]
        self.assertIn("person._template", with_templates)

    def test_scanned_counts_what_survived_the_filters(self) -> None:
        result = self.search("nothing-matches-this", type_filter="place")

        self.assertEqual(result.hits, [])
        self.assertEqual(result.scanned, len(self.store.list_ids(type_filter="place")))


class TestSearchParallelism(_ProjectCase):
    """The pool is an optimisation; it must be invisible in the answer."""

    def setUp(self) -> None:
        super().setUp()
        for index in range(120):
            self.store.store_object(f"note.n{index:03d}", f"Note {index}\nkeyword\n")

    def _ids(self, workers: str) -> list[str]:
        with patch.dict(os.environ, {"LENS_KB_SEARCH_WORKERS": workers}):
            return [hit.id for hit in self.search("keyword").hits]

    def test_the_parallel_scan_returns_exactly_the_serial_scan(self) -> None:
        self.assertEqual(self._ids("4"), self._ids("1"))

    def test_it_falls_back_to_a_serial_scan_when_no_pool_can_start(self) -> None:
        with patch(
            "lens.core.commands.kb_search.ProcessPoolExecutor",
            side_effect=OSError("no forking here"),
        ):
            with patch.dict(os.environ, {"LENS_KB_SEARCH_WORKERS": "4"}):
                result = self.search("keyword")

        self.assertEqual(len(result.hits), 120)


class TestList(_ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.store_object("person.rowan", "ROWAN\nA ranger.\nOf the north.\n")
        self.store.add_tags("person.rowan", ["pc"])

    def _list(self, **kwargs: Any) -> list[str]:
        return [e.id for e in kb_list(store=self.store, **kwargs)]

    def test_it_enumerates_project_and_dataset_together(self) -> None:
        ids = self._list()

        self.assertIn("person.rowan", ids)
        self.assertIn("rules.skirmish", ids)

    def test_it_is_id_ordered(self) -> None:
        ids = self._list()

        self.assertEqual(ids, sorted(ids))

    def test_an_entry_carries_tags_source_and_headline(self) -> None:
        entry = next(e for e in kb_list(store=self.store) if e.id == "person.rowan")

        self.assertEqual(entry.type, "person")
        self.assertEqual(entry.tags, ["pc"])
        self.assertEqual(entry.source.label, "project")
        self.assertEqual(entry.headline, "ROWAN\nA ranger.\nOf the north.")

    def test_ids_only_skips_reading_bodies(self) -> None:
        entries = kb_list(store=self.store, headlines=False)

        self.assertTrue(all(e.headline == "" for e in entries))

    def test_the_source_filter_splits_the_merge(self) -> None:
        self.assertNotIn("rules.skirmish", self._list(source="project"))
        self.assertNotIn("person.rowan", self._list(source="dataset"))

    def test_shadowed_finds_the_copy_on_write_forks(self) -> None:
        self.store.store_object("person.hero", "My own hero.\n")

        shadowed = self._list(shadowed=True)

        self.assertEqual(shadowed, ["person.hero"])

    def test_shadowed_is_empty_when_nothing_overrides_anything(self) -> None:
        self.assertEqual(self._list(shadowed=True), [])

    def test_templates_are_excluded_unless_asked_for(self) -> None:
        self.assertNotIn("person._template", self._list())
        self.assertIn("person._template", self._list(include_templates=True))


class TestRefsOutgoing(_ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.store_object("front.problem", "The problem.\n")
        self.store.store_object("front.problem-prep", "Prep notes.\n")
        self.store.store_object("place.tavern", "A tavern.\n")
        self.store.add_tags("front.problem", ["place.tavern", "place.nowhere"])

    def _kinds(self, canonical_id: str) -> list[tuple[str, str]]:
        result = self.refs(canonical_id, incoming=False)
        return [(ref.kind, ref.target) for ref in result.refs]

    def test_a_dot_tag_is_an_outgoing_link(self) -> None:
        self.assertIn(("tag-link", "place.tavern"), self._kinds("front.problem"))

    def test_a_dot_tag_pointing_nowhere_is_called_out(self) -> None:
        self.assertIn(("dangling-tag", "place.nowhere"), self._kinds("front.problem"))

    def test_a_facet_is_an_outgoing_link(self) -> None:
        """Facets are lexical, so nothing on disk records the relationship."""
        self.assertIn(("facet", "front.problem-prep"), self._kinds("front.problem"))

    def test_the_rules_companion_of_the_type_travels_with_the_object(self) -> None:
        self.store.store_object("rules.front", "How to run a front.\n")

        self.assertIn(("rules-companion", "rules.front"), self._kinds("front.problem"))

    def test_the_type_template_is_reported(self) -> None:
        self.store.set_template("front", "A front template.\n")

        self.assertIn(("template", "front._template"), self._kinds("front.problem"))

    def test_only_the_extra_reach_of_a_double_hop_is_listed(self) -> None:
        """A single `+` is the dot-tags already listed; `++` is the news."""
        self.store.store_object("region.north", "The north.\n")
        self.store.add_tags("place.tavern", ["region.north"])

        kinds = self._kinds("front.problem")

        self.assertIn(("hop++", "region.north"), kinds)
        self.assertNotIn(("hop++", "place.tavern"), kinds)

    def test_asking_for_out_only_returns_no_inbound_refs(self) -> None:
        result = self.refs("front.problem", incoming=False)

        self.assertEqual(result.incoming(), [])


class TestRefsIncoming(_ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.store_object("place.tavern", "A tavern.\n")
        self.store.store_object("front.problem", "The problem.\n")
        self.store.store_object("front.problem-prep", "Prep notes.\n")
        self.store.add_tags("front.problem", ["place.tavern"])

    def _refs(self, canonical_id: str) -> list[Ref]:
        return self.refs(canonical_id, outgoing=False).refs

    def _details(self, canonical_id: str, kind: str) -> list[str]:
        return [r.detail for r in self._refs(canonical_id) if r.kind == kind]

    def test_an_object_that_dot_tags_this_one_is_an_inbound_link(self) -> None:
        refs = self._refs("place.tavern")

        self.assertIn(("tag-link", "front.problem"), [(r.kind, r.target) for r in refs])

    def test_a_facet_names_the_object_it_is_a_facet_of(self) -> None:
        refs = self._refs("front.problem-prep")

        self.assertIn(("facet-of", "front.problem"), [(r.kind, r.target) for r in refs])

    def test_a_rules_object_reports_the_type_that_pulls_it(self) -> None:
        self.store.store_object("rules.front", "How to run a front.\n")

        refs = self._refs("rules.front")

        companion = [r for r in refs if r.kind == "rules-companion"]
        self.assertEqual([r.target for r in companion], ["front.*"])

    def test_a_dataset_module_registration_is_reported(self) -> None:
        """The manifest lives outside the repo; nothing in the tree names it."""
        refs = self._refs("rules.skirmish")

        module = [r for r in refs if r.kind == "module"]
        self.assertEqual([r.target for r in module], ["dataset:testing"])
        self.assertIn("play", module[0].detail)

    def test_a_front_matter_pin_names_the_node_and_the_line(self) -> None:
        self.write_node("[\n    kb_pin:\n    - place.tavern\n]: #\n\nKira waits.\n")

        refs = [r for r in self._refs("place.tavern") if r.kind == "narrative"]

        self.assertEqual(refs[0].target, "story@1")
        self.assertEqual(refs[0].detail, "kb_pin")

    def test_an_unpin_is_reported_too(self) -> None:
        self.write_node("[\n    kb_unpin:\n    - place.tavern\n]: #\n")

        self.assertEqual(self._details("place.tavern", "narrative"), ["kb_unpin"])

    def test_a_pin_that_reaches_the_object_by_expansion_names_the_route(self) -> None:
        """`front.problem+` never spells `place.tavern`; a grep would miss it."""
        self.write_node("[\n    kb_pin:\n    - front.problem+\n]: #\n")

        self.assertEqual(
            self._details("place.tavern", "narrative"),
            ["kb_pin via front.problem+"],
        )

    def test_a_pin_that_reaches_the_object_as_a_facet_names_the_route(self) -> None:
        self.write_node("[\n    kb_pin:\n    - front.problem\n]: #\n")

        self.assertEqual(
            self._details("front.problem-prep", "narrative"),
            ["kb_pin facet of front.problem"],
        )

    def test_a_pin_that_pulls_the_rules_companion_names_the_route(self) -> None:
        self.store.store_object("rules.front", "How to run a front.\n")
        self.write_node("[\n    kb_pin:\n    - front.problem\n]: #\n")

        self.assertEqual(
            self._details("rules.front", "narrative"),
            ["kb_pin rules companion of front.problem"],
        )

    def test_a_mention_annotation_is_reported_with_its_line(self) -> None:
        self.write_node("Kira waits.\n\n[mention: place.tavern]: #\n")

        refs = [r for r in self._refs("place.tavern") if r.kind == "narrative"]

        self.assertEqual((refs[0].target, refs[0].detail), ("story@3", "mention"))

    def test_an_include_annotation_is_reported(self) -> None:
        self.write_node("[include: place.tavern]: #\n")

        self.assertEqual(self._details("place.tavern", "narrative"), ["include"])

    def test_a_session_module_param_resolves_through_the_operator_prefix(self) -> None:
        """`module: skirmish` on a play session means `rules.skirmish`."""
        self.write_node("[play\n    module: skirmish\n]: #\n")

        self.assertEqual(
            self._details("rules.skirmish", "narrative"), ["play module"]
        )

    def test_every_narrative_tree_is_scanned_not_just_the_active_one(self) -> None:
        other = self.root / "narrative" / "side"
        other.mkdir(parents=True)
        (other / "_node.md").write_text(
            "[\n    kb_pin:\n    - place.tavern\n]: #\n", encoding="utf-8"
        )

        targets = [r.target for r in self._refs("place.tavern") if r.kind == "narrative"]

        self.assertIn("side@1", targets)

    def test_a_deleted_object_still_reports_who_referenced_it(self) -> None:
        self.write_node("[\n    kb_pin:\n    - place.ruin\n]: #\n")

        result = self.refs("place.ruin", outgoing=False)

        self.assertFalse(result.exists)
        self.assertEqual([r.detail for r in result.refs], ["kb_pin"])

    def test_a_malformed_id_is_a_lens_error(self) -> None:
        with self.assertRaises(LensException):
            self.refs("not an id")


class TestRendering(_ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.store_object("person.rowan", "ROWAN\nA ranger.\n\nShe waits.\n")

    def test_a_body_match_renders_as_id_line_text(self) -> None:
        result = self.search("She waits")
        hit = result.hits[0]

        self.assertEqual(
            format_match_line(hit, hit.matches[0]), "person.rowan:4:She waits."
        )

    def test_an_identity_match_renders_its_field_at_line_zero(self) -> None:
        result = self.search("rowan")
        hit = result.hits[0]

        self.assertEqual(
            format_match_line(hit, hit.matches[0]),
            "person.rowan:0:[id] person.rowan",
        )

    def test_rendered_lines_stay_in_line_order_across_merged_context(self) -> None:
        """Two matches share the lines between them; a later context line must
        not overtake an earlier match."""
        self.store.store_object("person.pair", "one\nhit\nhit\nfour\n")

        result = self.search("hit", context=2, type_filter="person")
        hit = next(h for h in result.hits if h.id == "person.pair")

        self.assertEqual(
            format_hit_lines(hit),
            [
                "person.pair-1-one",
                "person.pair:2:hit",
                "person.pair:3:hit",
                "person.pair-4-four",
                "person.pair-5-",
            ],
        )

    def test_a_gap_between_groups_is_marked_the_way_grep_marks_it(self) -> None:
        self.store.store_object(
            "person.gap", "hit\nb\nc\nd\ne\nf\ng\nhit\n"
        )

        result = self.search("hit", type_filter="person")
        hit = next(h for h in result.hits if h.id == "person.gap")

        self.assertEqual(
            format_hit_lines(hit), ["person.gap:1:hit", "--", "person.gap:8:hit"]
        )

    def test_the_search_payload_carries_matches_and_provenance(self) -> None:
        payload = search_payload(self.search("She waits"))

        self.assertEqual(payload["count"], 1)
        item = payload["items"][0]
        self.assertEqual(item["id"], "person.rowan")
        self.assertEqual(item["source"]["kind"], "project")
        self.assertEqual(item["matches"][0]["line"], 4)

    def test_the_list_payload_carries_ids_and_items(self) -> None:
        payload = list_payload(kb_list(store=self.store, type_filter="person"))

        self.assertIn("person.rowan", payload["ids"])
        self.assertTrue(all("source" in item for item in payload["items"]))

    def test_the_refs_payload_names_the_direction_of_each_edge(self) -> None:
        payload = refs_payload(self.refs("person.rowan"))

        self.assertEqual(payload["id"], "person.rowan")
        self.assertTrue(payload["exists"])
        self.assertTrue(
            all(ref["direction"] in ("out", "in") for ref in payload["refs"])
        )


if __name__ == "__main__":
    unittest.main()
