"""Unit tests for kb with-tag and tag-based back-traversal."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from lens.core.commands.kb import kb_with_tag
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeObject, KnowledgeStore
from lens.core.storage_text import kb_headline


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
        ["git", "commit", "-m", "init"],
        cwd=tmp, capture_output=True, check=True,
    )


def _make_project_with_datasets(tmp: Path, datasets: list[str]) -> None:
    """Create a minimal Lens project that selects one or more datasets."""
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    datasets_list = ", ".join(f"\"{name}\"" for name in datasets)
    (tmp / "lens.toml").write_text(
        "[project]\n"
        f"datasets = [{datasets_list}]\n"
    )
    (tmp / "knowledge").mkdir()
    (tmp / "knowledge" / "tags.toml").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )


def _build_map_fixture(store: KnowledgeStore) -> None:
    """Build kingdom -> cities -> taverns (Up map: children tag parent; BFS follows object IDs as tags)."""
    store.store_object("location.kingdom", "The kingdom.")
    store.store_object("location.city_a", "City A.")
    store.store_object("location.city_b", "City B.")
    store.store_object("location.tavern_1", "Tavern 1.")
    store.store_object("location.tavern_2", "Tavern 2.")
    store.store_object("location.tavern_3", "Tavern 3.")
    store.add_tags("location.kingdom", ["location.kingdom"])
    store.add_tags("location.city_a", ["location.kingdom"])
    store.add_tags("location.city_b", ["location.kingdom"])
    store.add_tags("location.tavern_1", ["location.city_a"])
    store.add_tags("location.tavern_2", ["location.city_a"])
    store.add_tags("location.tavern_3", ["location.city_b"])


def _build_part_fixture(store: KnowledgeStore) -> None:
    """Build part.head: PCs have part tags; --same-type filters to part.* only (empty)."""
    store.store_object("part.head", "Head")
    store.store_object("part.body", "Body")
    store.store_object("person.amy", "Amy")
    store.store_object("person.carlos", "Carlos")
    store.add_tags("person.amy", ["part.head", "part.body"])
    store.add_tags("person.carlos", ["part.head"])


def _build_cross_type_fixture(store: KnowledgeStore) -> None:
    """Build location.* and front.* with cross-type dot-tags (dungeon in region, curse links to dungeon)."""
    store.store_object("location.region", "The region.")
    store.store_object("location.dungeon", "A dungeon.")
    store.store_object("front.curse", "A curse front.")
    store.add_tags("location.dungeon", ["location.region"])
    store.add_tags("front.curse", ["location.dungeon"])


def _build_cycle_fixture(store: KnowledgeStore) -> None:
    """Build A <-> B cycle via dot-tags."""
    store.store_object("location.a", "A")
    store.store_object("location.b", "B")
    store.add_tags("location.a", ["location.b"])
    store.add_tags("location.b", ["location.a"])
    store.add_tags("location.a", ["start"])
    store.store_object("other.x", "X")
    store.add_tags("other.x", ["start"])


def _build_multi_layer_fixture(store: KnowledgeStore) -> None:
    """Build tavern -> city -> kingdom -> continent as a linear dot-tag chain."""
    store.store_object("location.continent", "Continent")
    store.store_object("location.kingdom", "Kingdom")
    store.store_object("location.city", "City")
    store.store_object("location.tavern", "Tavern")
    store.add_tags("location.kingdom", ["location.continent"])
    store.add_tags("location.city", ["location.kingdom"])
    store.add_tags("location.tavern", ["location.city"])


class TestGetIdsWithTag(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        self.store = KnowledgeStore(self.root)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_tag_returns_empty(self) -> None:
        self.assertEqual(self.store.get_ids_with_tag("nonexistent"), [])

    def test_returns_sorted_ids(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        self.store.add_tags("place.nyc", ["featured"])
        self.store.add_tags("place.boston", ["featured"])
        ids = self.store.get_ids_with_tag("featured")
        self.assertEqual(ids, ["place.boston", "place.nyc"])

    def test_normalizes_tag_case(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.add_tags("place.nyc", ["Featured"])
        self.assertEqual(self.store.get_ids_with_tag("FEATURED"), ["place.nyc"])
        self.assertEqual(self.store.get_ids_with_tag("featured"), ["place.nyc"])

    def test_get_ids_with_all_tags_empty_returns_empty(self) -> None:
        self.assertEqual(self.store.get_ids_with_all_tags([]), [])

    def test_get_ids_with_all_tags_single_same_as_get_ids_with_tag(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.add_tags("place.nyc", ["featured"])
        self.assertEqual(
            self.store.get_ids_with_all_tags(["featured"]),
            self.store.get_ids_with_tag("featured"),
        )

    def test_get_ids_with_all_tags_two_tags_returns_intersection(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        self.store.store_object("place.chicago", "Chicago")
        self.store.add_tags("place.nyc", ["featured", "pc"])
        self.store.add_tags("place.boston", ["featured"])
        self.store.add_tags("place.chicago", ["pc"])
        ids = self.store.get_ids_with_all_tags(["featured", "pc"])
        self.assertEqual(ids, ["place.nyc"])

    def test_get_ids_with_all_tags_three_tags_returns_intersection(self) -> None:
        self.store.store_object("place.a", "A")
        self.store.store_object("place.b", "B")
        self.store.add_tags("place.a", ["t1", "t2", "t3"])
        self.store.add_tags("place.b", ["t1", "t2"])
        self.assertEqual(self.store.get_ids_with_all_tags(["t1", "t2", "t3"]), ["place.a"])
        self.assertEqual(self.store.get_ids_with_all_tags(["t1", "t2"]), ["place.a", "place.b"])

    def test_get_ids_with_all_tags_no_match_returns_empty(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.add_tags("place.nyc", ["featured"])
        self.assertEqual(self.store.get_ids_with_all_tags(["featured", "nonexistent"]), [])


class TestTraverseByDotTags(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        self.store = KnowledgeStore(self.root)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_map_traversal_kingdom_cities_taverns(self) -> None:
        _build_map_fixture(self.store)
        root_ids, layers = self.store.traverse_by_dot_tags(["location.kingdom"], same_type_only=False)
        self.assertEqual(set(root_ids), {"location.kingdom", "location.city_a", "location.city_b"})
        by_tag = dict(layers)
        self.assertIn("location.city_a", by_tag)
        self.assertIn("location.city_b", by_tag)
        self.assertEqual(set(by_tag["location.city_a"]), {"location.tavern_1", "location.tavern_2"})
        self.assertEqual(set(by_tag["location.city_b"]), {"location.tavern_3"})

    def test_same_type_only_filters_traversal(self) -> None:
        _build_cross_type_fixture(self.store)
        _, layers_same = self.store.traverse_by_dot_tags(["location.region"], same_type_only=True)
        by_tag = dict(layers_same)
        self.assertIn("location.dungeon", by_tag)
        self.assertEqual(set(by_tag["location.dungeon"]), set())

    def test_same_type_ignored_when_starting_tag_not_dot(self) -> None:
        self.store.store_object("location.dungeon", "Dungeon")
        self.store.store_object("front.curse", "Curse")
        self.store.add_tags("location.dungeon", ["simple_tag", "front.curse"])
        self.store.add_tags("front.curse", ["location.dungeon"])
        root_ids, layers = self.store.traverse_by_dot_tags(["simple_tag"], same_type_only=True)
        self.assertIn("location.dungeon", root_ids)
        tag_set = {t for t, _ in layers}
        self.assertIn("location.dungeon", tag_set)
        self.assertIn("front.curse", tag_set)

    def test_cycle_does_not_loop(self) -> None:
        _build_cycle_fixture(self.store)
        root_ids, layers = self.store.traverse_by_dot_tags(["start"], same_type_only=False)
        self.assertIn("location.a", root_ids)
        self.assertIn("other.x", root_ids)
        by_tag = dict(layers)
        self.assertIn("location.a", by_tag)
        self.assertIn("location.b", by_tag)
        self.assertEqual(set(by_tag["location.a"]), {"location.b"})
        self.assertEqual(set(by_tag["location.b"]), {"location.a"})
        self.assertLessEqual(len(layers), 4)

    def test_empty_root_returns_empty_layers(self) -> None:
        _, layers = self.store.traverse_by_dot_tags(["nonexistent"], same_type_only=False)
        self.assertEqual(layers, [])

    def test_part_head_same_type_filters_to_empty(self) -> None:
        _build_part_fixture(self.store)
        root_ids, layers = self.store.traverse_by_dot_tags(["part.head"], same_type_only=True)
        self.assertEqual(root_ids, [])
        self.assertEqual(layers, [])

    def test_part_head_recurse_follows_dot_tags_from_objects(self) -> None:
        _build_part_fixture(self.store)
        root_ids, layers = self.store.traverse_by_dot_tags(["part.head"], same_type_only=False)
        self.assertEqual(set(root_ids), {"person.amy", "person.carlos"})
        by_tag = dict(layers)
        self.assertIn("part.body", by_tag)
        self.assertEqual(set(by_tag["part.body"]), {"person.amy"})

    def test_traverse_multi_tag_root_is_intersection(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        self.store.store_object("place.chicago", "Chicago")
        self.store.add_tags("place.nyc", ["featured", "pc"])
        self.store.add_tags("place.boston", ["featured"])
        self.store.add_tags("place.chicago", ["pc"])
        root_ids, _ = self.store.traverse_by_dot_tags(["featured", "pc"], same_type_only=False)
        self.assertEqual(root_ids, ["place.nyc"])


class TestKbWithTagCore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        self.store = KnowledgeStore(self.root)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_with_tag(
        self,
        tags: list[str],
        *,
        expand: bool = False,
        recurse: int | None = None,
        same_type_only: bool = False,
    ) -> tuple[
        list[str],
        list[tuple[str, list[str]]] | None,
        dict[str, KnowledgeObject] | None
    ]:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            result = kb_with_tag(
                tags,
                expand=expand,
                recurse=recurse,
                same_type_only=same_type_only,
            )
        return result.ids, result.layers, result.objects

    def test_base_returns_ids_only(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.add_tags("place.nyc", ["featured"])
        ids, layers, objects = self._run_with_tag(["featured"])
        self.assertEqual(ids, ["place.nyc"])
        self.assertIsNone(layers)
        self.assertIsNone(objects)

    def test_expand_returns_objects(self) -> None:
        self.store.store_object("place.nyc", "Big city")
        self.store.add_tags("place.nyc", ["featured"])
        ids, layers, objects = self._run_with_tag(["featured"], expand=True)
        self.assertEqual(ids, ["place.nyc"])
        self.assertIsNone(layers)
        self.assertIsNotNone(objects)
        self.assertIn("place.nyc", objects or {})
        self.assertEqual((objects or {})["place.nyc"].text.strip(), "Big city")

    def test_recurse_returns_layers(self) -> None:
        _build_map_fixture(self.store)
        ids, layers, objects = self._run_with_tag(["location.kingdom"], recurse=0)
        self.assertEqual(set(ids), {"location.kingdom", "location.city_a", "location.city_b"})
        self.assertIsNotNone(layers)
        by_tag = dict(layers or [])
        self.assertIn("location.city_a", by_tag)
        self.assertIn("location.city_b", by_tag)
        self.assertEqual(set(by_tag["location.city_a"]), {"location.tavern_1", "location.tavern_2"})
        self.assertIsNone(objects)

    def test_recurse_expand_returns_objects_for_all_layers(self) -> None:
        _build_map_fixture(self.store)
        ids, layers, objects = self._run_with_tag(
            ["location.kingdom"], recurse=0, expand=True
        )
        self.assertIsNotNone(objects)
        all_ids = set(ids)
        for _, child_ids in layers or []:
            all_ids.update(child_ids)
        for oid in all_ids:
            self.assertIn(oid, objects or {}, f"expected {oid} in objects")

    def test_same_type_base_filters_root_ids(self) -> None:
        _build_part_fixture(self.store)
        ids, layers, objects = self._run_with_tag(["part.head"], same_type_only=True)
        self.assertEqual(ids, [])
        self.assertIsNone(layers)
        self.assertIsNone(objects)

    def test_same_type_recurse_returns_empty_when_no_matching_roots(self) -> None:
        _build_part_fixture(self.store)
        ids, layers, objects = self._run_with_tag(
            ["part.head"], recurse=0, same_type_only=True
        )
        self.assertEqual(ids, [])
        self.assertEqual(layers or [], [])
        self.assertIsNone(objects)

    def test_multi_tag_returns_only_objects_with_all_tags(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        self.store.store_object("place.chicago", "Chicago")
        self.store.add_tags("place.nyc", ["featured", "pc"])
        self.store.add_tags("place.boston", ["featured"])
        self.store.add_tags("place.chicago", ["pc"])
        ids, _, _ = self._run_with_tag(["featured", "pc"])
        self.assertEqual(ids, ["place.nyc"])

    def test_or_group_returns_objects_matching_any_tag_in_or_group(self) -> None:
        self.store.store_object("stat.ghoul", "Ghoul")
        self.store.store_object("stat.wight", "Wight")
        self.store.store_object("stat.skeleton", "Skeleton")
        self.store.add_tags("stat.ghoul", ["type:undead", "cr:1"])
        self.store.add_tags("stat.wight", ["type:undead", "cr:3"])
        self.store.add_tags("stat.skeleton", ["type:undead", "cr:1-4"])
        ids, _, _ = self._run_with_tag(["type:undead", "(cr:1 cr:2 cr:3)"])
        self.assertEqual(set(ids), {"stat.ghoul", "stat.wight"})

    def test_empty_tags_raises(self) -> None:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            with self.assertRaises(LensException) as ctx:
                kb_with_tag([], expand=False, recurse=None)
        self.assertIn("at least one tag", str(ctx.exception))

    def test_recurse_depth_1_limits_layers(self) -> None:
        _build_map_fixture(self.store)
        ids, layers, objects = self._run_with_tag(["location.kingdom"], recurse=1)
        self.assertEqual(set(ids), {"location.kingdom", "location.city_a", "location.city_b"})
        self.assertIsNotNone(layers)
        tag_names = [t for t, _ in layers or []]
        self.assertEqual(set(tag_names), {"location.city_a", "location.city_b"})
        self.assertIsNone(objects)

    def test_multi_layer_recurse_depths(self) -> None:
        _build_multi_layer_fixture(self.store)
        # No recurse: only direct matches for the starting tag.
        ids, layers, objects = self._run_with_tag(["location.continent"], recurse=None)
        self.assertEqual(ids, ["location.kingdom"])
        self.assertIsNone(layers)
        self.assertIsNone(objects)

        # Depth 1: roots plus one hop (kingdom -> city).
        ids, layers, objects = self._run_with_tag(["location.continent"], recurse=1)
        self.assertEqual(ids, ["location.kingdom"])
        by_tag = dict(layers or [])
        self.assertIn("location.kingdom", by_tag)
        self.assertEqual(by_tag["location.kingdom"], ["location.city"])
        self.assertNotIn("location.city", by_tag)
        self.assertIsNone(objects)

        # Depth 2: include tavern as well.
        ids, layers, objects = self._run_with_tag(["location.continent"], recurse=2)
        self.assertEqual(ids, ["location.kingdom"])
        by_tag = dict(layers or [])
        self.assertIn("location.kingdom", by_tag)
        self.assertIn("location.city", by_tag)
        self.assertEqual(by_tag["location.kingdom"], ["location.city"])
        self.assertEqual(by_tag["location.city"], ["location.tavern"])


class TestTypeAsTag(unittest.TestCase):
    """A type is a tag: `design` finds every design.* with no tagging required.

    Discovery has to work off what an object already is. A parallel hand-kept tag
    saying the same word as the id would go stale, and the objects missing from it
    would be invisible rather than merely unlabelled.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        self.store = KnowledgeStore(self.root)
        self.store.store_object(
            "design.clock", "CLOCK\n\nA countdown you can point at.\n\nLong body."
        )
        self.store.store_object("design.mute", "\n\n\nNo self-description here.")
        self.store.store_object("place.nyc", "NYC")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, tags: list[str], **kwargs: object) -> object:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            return kb_with_tag(tags, **kwargs)  # type: ignore[arg-type]

    def test_a_bare_type_matches_every_object_of_that_type(self) -> None:
        result = self._run(["design"])

        self.assertEqual(result.ids, ["design.clock", "design.mute"])  # type: ignore[attr-defined]

    def test_a_type_ands_with_a_real_tag(self) -> None:
        self.store.add_tags("design.clock", ["featured"])

        result = self._run(["design", "featured"])

        self.assertEqual(result.ids, ["design.clock"])  # type: ignore[attr-defined]

    def test_types_are_listed_as_tags(self) -> None:
        """A discovery tool that hides half of what it can find is a trap."""
        self.assertIn("design", self.store.list_unique_tags())

    def test_a_template_is_not_an_object_of_its_type(self) -> None:
        self.store.set_template("design", "# [DESIGN MODULE]: {TITLE}")

        result = self._run(["design"])

        self.assertNotIn("design._template", result.ids)  # type: ignore[attr-defined]

    def test_headlines_accompany_the_id_list(self) -> None:
        result = self._run(["design"])

        self.assertEqual(
            result.id_to_headline,  # type: ignore[attr-defined]
            {"design.clock": "CLOCK\nA countdown you can point at."},
        )

    def test_expand_does_not_pay_for_headlines(self) -> None:
        """With whole bodies on screen the headline is already the first line of one."""
        result = self._run(["design"], expand=True)

        self.assertIsNone(result.id_to_headline)  # type: ignore[attr-defined]


class TestKbHeadline(unittest.TestCase):
    """The first-three-lines policy: what a KB object says about itself."""

    def test_title_blank_purpose_is_the_canonical_shape(self) -> None:
        self.assertEqual(
            kb_headline("D&D COMBAT RULES\n\nRunning a fight.\n\nSTARTING COMBAT\n"),
            "D&D COMBAT RULES\nRunning a fight.",
        )

    def test_nothing_past_the_third_line_is_read(self) -> None:
        self.assertEqual(
            kb_headline("One\nTwo\nThree\nFour\n"), "One\nTwo\nThree"
        )

    def test_annotation_front_matter_does_not_spend_the_budget(self) -> None:
        """A template declaring default tags still gets three lines of its own."""
        text = "[\n    tags: state\n]: #\nTracker\n\nLive combat state.\n\nBody.\n"

        self.assertEqual(kb_headline(text), "Tracker\nLive combat state.")

    def test_a_one_line_html_comment_is_unwrapped(self) -> None:
        """Templates keep their usage note in a comment so it never lands in copies."""
        text = "<!-- A prepared situation. Usage: pin when the scene starts. -->\nName\n"

        self.assertEqual(
            kb_headline(text),
            "A prepared situation. Usage: pin when the scene starts.\nName",
        )

    def test_a_body_that_never_names_itself_has_no_headline(self) -> None:
        self.assertEqual(kb_headline("\n\n\nBody starts on line four.\n"), "")


class TestWithTagCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        self.store = KnowledgeStore(self.root)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_with_tag_cli(
        self,
        tags: list[str],
        *,
        expand: bool = False,
        recurse: int | None = None,
        same_type_only: bool = False,
        type_filter: str | None = None,
    ) -> str:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
                from lens.cli.commands.kb import with_tag

                old_stdout = sys.stdout
                try:
                    buf = StringIO()
                    sys.stdout = buf
                    # Typer command called as a plain function: an Option left
                    # unset stays an OptionInfo, which is truthy. Pass the flag.
                    with_tag(
                        tags,
                        expand=expand,
                        recurse=recurse,
                        same_type_only=same_type_only,
                        type_filter=type_filter,
                        as_json=False,
                    )
                    return buf.getvalue()
                finally:
                    sys.stdout = old_stdout

    def test_cli_base_prints_ids_with_headline(self) -> None:
        self.store.store_object("place.nyc", "NYC\n\nA city that never sleeps.\n\nBody.")
        self.store.add_tags("place.nyc", ["featured"])
        out = self._run_with_tag_cli(["featured"])
        self.assertEqual(
            out.strip(),
            "place.nyc  [featured]  SOURCE=project\n    NYC\n    A city that never sleeps.",
        )
        self.assertNotIn("Body.", out)

    def test_cli_expand_prints_objects(self) -> None:
        self.store.store_object("place.nyc", "Big city")
        self.store.add_tags("place.nyc", ["featured"])
        out = self._run_with_tag_cli(["featured"], expand=True)
        self.assertIn("KB['place.nyc']", out)
        self.assertIn("Big city", out)

    def test_cli_recurse_prints_headers_and_ids(self) -> None:
        _build_map_fixture(self.store)
        out = self._run_with_tag_cli(["location.kingdom"], recurse=0)
        self.assertIn("# Objects with tag 'location.kingdom'", out)
        self.assertIn("location.kingdom", out)
        self.assertIn("location.city_a", out)
        self.assertIn("> with-tag 'location.city_a'", out)
        self.assertIn("location.tavern_1", out)
        self.assertIn("location.tavern_2", out)
        self.assertIn("> with-tag 'location.city_b'", out)
        self.assertIn("location.tavern_3", out)

    def test_cli_same_type_prints_nothing(self) -> None:
        _build_part_fixture(self.store)
        out = self._run_with_tag_cli(["part.head"], same_type_only=True)
        self.assertEqual(out.strip(), "")

    def test_cli_same_type_recurse_prints_nothing(self) -> None:
        _build_part_fixture(self.store)
        out = self._run_with_tag_cli(["part.head"], recurse=0, same_type_only=True)
        self.assertEqual(out.strip(), "")

    def test_cli_recurse_follows_dot_tags_not_object_ids_as_tags(self) -> None:
        _build_part_fixture(self.store)
        out = self._run_with_tag_cli(["part.head"], recurse=0)
        self.assertIn("# Objects with tag 'part.head'", out)
        self.assertIn("person.amy", out)
        self.assertIn("person.carlos", out)
        self.assertIn("> with-tag 'part.body'", out)
        self.assertNotIn("> with-tag 'person.amy'", out)
        self.assertNotIn("> with-tag 'person.carlos'", out)

    def test_cli_recurse_expand_prints_all_objects_by_layer(self) -> None:
        _build_map_fixture(self.store)
        out = self._run_with_tag_cli(["location.kingdom"], recurse=0, expand=True)
        self.assertIn("# From tag 'location.city_a'", out)
        self.assertIn("KB['location.tavern_1']", out)
        self.assertIn("KB['location.tavern_2']", out)
        self.assertIn("KB['location.tavern_3']", out)
        self.assertIn("Tavern 1.", out)
        self.assertIn("Tavern 2.", out)
        self.assertIn("Tavern 3.", out)

    def test_cli_multi_tag_prints_only_ids_with_all_tags(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        self.store.store_object("place.chicago", "Chicago")
        self.store.add_tags("place.nyc", ["featured", "pc"])
        self.store.add_tags("place.boston", ["featured"])
        self.store.add_tags("place.chicago", ["pc"])
        out = self._run_with_tag_cli(["featured", "pc"])
        self.assertEqual(out.strip(), "place.nyc  [featured pc]  SOURCE=project\n    NYC")

    def test_cli_recurse_depth_1_omits_deeper_children(self) -> None:
        _build_map_fixture(self.store)
        out = self._run_with_tag_cli(["location.kingdom"], recurse=1)
        self.assertIn("# Objects with tag 'location.kingdom'", out)
        self.assertIn("location.kingdom", out)
        self.assertIn("location.city_a", out)
        self.assertIn("location.city_b", out)
        self.assertIn("> with-tag 'location.city_a'", out)
        self.assertIn("> with-tag 'location.city_b'", out)
        self.assertIn("location.tavern_1", out)
        self.assertIn("location.tavern_2", out)
        self.assertIn("location.tavern_3", out)

    def test_cli_multi_layer_recurse_depths(self) -> None:
        _build_multi_layer_fixture(self.store)

        # No recurse: only kingdom (direct matches for 'location.continent').
        out = self._run_with_tag_cli(["location.continent"])
        self.assertNotIn("> with-tag", out)
        self.assertIn("location.kingdom", out)
        self.assertNotIn("location.city", out)
        self.assertNotIn("location.tavern", out)

        # Depth 1: add city as children of kingdom.
        out = self._run_with_tag_cli(["location.continent"], recurse=1)
        self.assertIn("# Objects with tag 'location.continent'", out)
        self.assertIn("location.kingdom", out)
        self.assertIn("> with-tag 'location.kingdom'", out)
        self.assertIn("location.city", out)
        self.assertNotIn("location.tavern", out)

        # Depth 2: include tavern as well (children of city).
        out = self._run_with_tag_cli(["location.continent"], recurse=2)
        self.assertIn("# Objects with tag 'location.continent'", out)
        self.assertIn("location.kingdom", out)
        self.assertIn("location.city", out)
        self.assertIn("location.tavern", out)
        self.assertIn("> with-tag 'location.kingdom'", out)
        self.assertIn("> with-tag 'location.city'", out)


class TestKbWithTagDatasets(unittest.TestCase):
    """Ensure kb with-tag sees objects from selected datasets."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        # Select the bundled 'testing' dataset declared in datasets/testing/.
        _make_project_with_datasets(self.root, ["testing"])
        # Use the real KnowledgeStore.for_project so dataset stores are attached.
        self.store = KnowledgeStore.for_project(self.root)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_with_tag(
        self,
        tags: list[str],
        *,
        expand: bool = False,
        recurse: int | None = None,
        same_type_only: bool = False,
    ) -> tuple[
        list[str],
        list[tuple[str, list[str]]] | None,
        dict[str, KnowledgeObject] | None,
    ]:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            result = kb_with_tag(
                tags,
                expand=expand,
                recurse=recurse,
                same_type_only=same_type_only,
            )
        return result.ids, result.layers, result.objects

    def _run_with_tag_cli(
        self,
        tags: list[str],
        *,
        expand: bool = False,
        recurse: int | None = None,
        same_type_only: bool = False,
        type_filter: str | None = None,
    ) -> str:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
                from lens.cli.commands.kb import with_tag

                old_stdout = sys.stdout
                try:
                    buf = StringIO()
                    sys.stdout = buf
                    # Typer command called as a plain function: an Option left
                    # unset stays an OptionInfo, which is truthy. Pass the flag.
                    with_tag(
                        tags,
                        expand=expand,
                        recurse=recurse,
                        same_type_only=same_type_only,
                        type_filter=type_filter,
                        as_json=False,
                    )
                    return buf.getvalue()
                finally:
                    sys.stdout = old_stdout

    def test_base_uses_dataset_tags_index(self) -> None:
        # The 'testing' dataset defines tag 'protagonist' for person.hero only.
        ids, layers, objects = self._run_with_tag(["protagonist"])
        self.assertEqual(ids, ["person.hero"])
        self.assertIsNone(layers)
        self.assertIsNone(objects)

    def test_recurse_uses_dataset_tag_roots(self) -> None:
        # The dataset establishes the tag 'place.dungeon' on two person objects.
        ids, layers, objects = self._run_with_tag(["place.dungeon"], recurse=0)
        # Both hero and villain live in the dataset and share the tag.
        self.assertEqual(set(ids), {"person.hero", "person.villain"})
        # There is no further dot-tag chain, so layers stay empty.
        self.assertEqual(layers or [], [])
        self.assertIsNone(objects)

    def test_dataset_objects_show_tags_in_cli_output(self) -> None:
        """Tags for dataset-only objects must appear when with-tag is run from a project."""
        out = self._run_with_tag_cli(["protagonist"])
        self.assertIn("person.hero", out)
        self.assertIn("[", out)
        self.assertIn("protagonist", out)
