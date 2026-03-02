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
from lens.core.knowledge import KnowledgeObject, KnowledgeStore


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


def _build_map_fixture(store: KnowledgeStore) -> None:
    """Build kingdom -> cities -> taverns (Up map: children tag parent; BFS follows object IDs as tags)."""
    store.store_object("loc.kingdom", "The kingdom.")
    store.store_object("loc.city_a", "City A.")
    store.store_object("loc.city_b", "City B.")
    store.store_object("loc.tavern_1", "Tavern 1.")
    store.store_object("loc.tavern_2", "Tavern 2.")
    store.store_object("loc.tavern_3", "Tavern 3.")
    store.add_tags("loc.kingdom", ["loc.kingdom"])
    store.add_tags("loc.city_a", ["loc.kingdom"])
    store.add_tags("loc.city_b", ["loc.kingdom"])
    store.add_tags("loc.tavern_1", ["loc.city_a"])
    store.add_tags("loc.tavern_2", ["loc.city_a"])
    store.add_tags("loc.tavern_3", ["loc.city_b"])


def _build_part_fixture(store: KnowledgeStore) -> None:
    """Build part.head: PCs have part tags; --same-type filters to part.* only (empty)."""
    store.store_object("part.head", "Head")
    store.store_object("part.body", "Body")
    store.store_object("person.amy", "Amy")
    store.store_object("person.carlos", "Carlos")
    store.add_tags("person.amy", ["part.head", "part.body"])
    store.add_tags("person.carlos", ["part.head"])


def _build_cross_type_fixture(store: KnowledgeStore) -> None:
    """Build loc.* and front.* with cross-type dot-tags (dungeon in region, curse links to dungeon)."""
    store.store_object("loc.region", "The region.")
    store.store_object("loc.dungeon", "A dungeon.")
    store.store_object("front.curse", "A curse front.")
    store.add_tags("loc.dungeon", ["loc.region"])
    store.add_tags("front.curse", ["loc.dungeon"])


def _build_cycle_fixture(store: KnowledgeStore) -> None:
    """Build A <-> B cycle via dot-tags."""
    store.store_object("loc.a", "A")
    store.store_object("loc.b", "B")
    store.add_tags("loc.a", ["loc.b"])
    store.add_tags("loc.b", ["loc.a"])
    store.add_tags("loc.a", ["start"])
    store.store_object("other.x", "X")
    store.add_tags("other.x", ["start"])


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
        root_ids, layers = self.store.traverse_by_dot_tags("loc.kingdom", same_type_only=False)
        self.assertEqual(set(root_ids), {"loc.kingdom", "loc.city_a", "loc.city_b"})
        by_tag = dict(layers)
        self.assertIn("loc.city_a", by_tag)
        self.assertIn("loc.city_b", by_tag)
        self.assertEqual(set(by_tag["loc.city_a"]), {"loc.tavern_1", "loc.tavern_2"})
        self.assertEqual(set(by_tag["loc.city_b"]), {"loc.tavern_3"})

    def test_same_type_only_filters_traversal(self) -> None:
        _build_cross_type_fixture(self.store)
        _, layers_same = self.store.traverse_by_dot_tags("loc.region", same_type_only=True)
        by_tag = dict(layers_same)
        self.assertIn("loc.dungeon", by_tag)
        self.assertEqual(set(by_tag["loc.dungeon"]), set())

    def test_same_type_ignored_when_starting_tag_not_dot(self) -> None:
        self.store.store_object("loc.dungeon", "Dungeon")
        self.store.store_object("front.curse", "Curse")
        self.store.add_tags("loc.dungeon", ["simple_tag", "front.curse"])
        self.store.add_tags("front.curse", ["loc.dungeon"])
        root_ids, layers = self.store.traverse_by_dot_tags("simple_tag", same_type_only=True)
        self.assertIn("loc.dungeon", root_ids)
        tag_set = {t for t, _ in layers}
        self.assertIn("loc.dungeon", tag_set)
        self.assertIn("front.curse", tag_set)

    def test_cycle_does_not_loop(self) -> None:
        _build_cycle_fixture(self.store)
        root_ids, layers = self.store.traverse_by_dot_tags("start", same_type_only=False)
        self.assertIn("loc.a", root_ids)
        self.assertIn("other.x", root_ids)
        by_tag = dict(layers)
        self.assertIn("loc.a", by_tag)
        self.assertIn("loc.b", by_tag)
        self.assertEqual(set(by_tag["loc.a"]), {"loc.b"})
        self.assertEqual(set(by_tag["loc.b"]), {"loc.a"})
        self.assertLessEqual(len(layers), 4)

    def test_empty_root_returns_empty_layers(self) -> None:
        _, layers = self.store.traverse_by_dot_tags("nonexistent", same_type_only=False)
        self.assertEqual(layers, [])

    def test_part_head_same_type_filters_to_empty(self) -> None:
        _build_part_fixture(self.store)
        root_ids, layers = self.store.traverse_by_dot_tags("part.head", same_type_only=True)
        self.assertEqual(root_ids, [])
        self.assertEqual(layers, [])

    def test_part_head_recurse_follows_dot_tags_from_objects(self) -> None:
        _build_part_fixture(self.store)
        root_ids, layers = self.store.traverse_by_dot_tags("part.head", same_type_only=False)
        self.assertEqual(set(root_ids), {"person.amy", "person.carlos"})
        by_tag = dict(layers)
        self.assertIn("part.body", by_tag)
        self.assertEqual(set(by_tag["part.body"]), {"person.amy"})


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
        tag: str,
        *,
        expand: bool = False,
        recurse: bool = False,
        same_type_only: bool = False,
    ) -> tuple[
        list[str],
        list[tuple[str, list[str]]] | None,
        dict[str, KnowledgeObject] | None
    ]:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            result = kb_with_tag(tag, expand=expand, recurse=recurse, same_type_only=same_type_only)
        return result.ids, result.layers, result.objects

    def test_base_returns_ids_only(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.add_tags("place.nyc", ["featured"])
        ids, layers, objects = self._run_with_tag("featured")
        self.assertEqual(ids, ["place.nyc"])
        self.assertIsNone(layers)
        self.assertIsNone(objects)

    def test_expand_returns_objects(self) -> None:
        self.store.store_object("place.nyc", "Big city")
        self.store.add_tags("place.nyc", ["featured"])
        ids, layers, objects = self._run_with_tag("featured", expand=True)
        self.assertEqual(ids, ["place.nyc"])
        self.assertIsNone(layers)
        self.assertIsNotNone(objects)
        self.assertIn("place.nyc", objects or {})
        self.assertEqual((objects or {})["place.nyc"].text.strip(), "Big city")

    def test_recurse_returns_layers(self) -> None:
        _build_map_fixture(self.store)
        ids, layers, objects = self._run_with_tag("loc.kingdom", recurse=True)
        self.assertEqual(set(ids), {"loc.kingdom", "loc.city_a", "loc.city_b"})
        self.assertIsNotNone(layers)
        by_tag = dict(layers or [])
        self.assertIn("loc.city_a", by_tag)
        self.assertIn("loc.city_b", by_tag)
        self.assertEqual(set(by_tag["loc.city_a"]), {"loc.tavern_1", "loc.tavern_2"})
        self.assertIsNone(objects)

    def test_recurse_expand_returns_objects_for_all_layers(self) -> None:
        _build_map_fixture(self.store)
        ids, layers, objects = self._run_with_tag(
            "loc.kingdom", recurse=True, expand=True
        )
        self.assertIsNotNone(objects)
        all_ids = set(ids)
        for _, child_ids in layers or []:
            all_ids.update(child_ids)
        for oid in all_ids:
            self.assertIn(oid, objects or {}, f"expected {oid} in objects")

    def test_same_type_base_filters_root_ids(self) -> None:
        _build_part_fixture(self.store)
        ids, layers, objects = self._run_with_tag("part.head", same_type_only=True)
        self.assertEqual(ids, [])
        self.assertIsNone(layers)
        self.assertIsNone(objects)

    def test_same_type_recurse_returns_empty_when_no_matching_roots(self) -> None:
        _build_part_fixture(self.store)
        ids, layers, objects = self._run_with_tag(
            "part.head", recurse=True, same_type_only=True
        )
        self.assertEqual(ids, [])
        self.assertEqual(layers or [], [])
        self.assertIsNone(objects)


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
        tag: str,
        *,
        expand: bool = False,
        recurse: bool = False,
        same_type_only: bool = False,
    ) -> str:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
                from lens.cli.commands.kb import with_tag

                old_stdout = sys.stdout
                try:
                    buf = StringIO()
                    sys.stdout = buf
                    with_tag(
                        tag,
                        expand=expand,
                        recurse=recurse,
                        same_type_only=same_type_only,
                    )
                    return buf.getvalue()
                finally:
                    sys.stdout = old_stdout

    def test_cli_base_prints_ids(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.add_tags("place.nyc", ["featured"])
        out = self._run_with_tag_cli("featured")
        self.assertEqual(out.strip(), "place.nyc")

    def test_cli_expand_prints_objects(self) -> None:
        self.store.store_object("place.nyc", "Big city")
        self.store.add_tags("place.nyc", ["featured"])
        out = self._run_with_tag_cli("featured", expand=True)
        self.assertIn("KB['place.nyc']", out)
        self.assertIn("Big city", out)

    def test_cli_recurse_prints_headers_and_ids(self) -> None:
        _build_map_fixture(self.store)
        out = self._run_with_tag_cli("loc.kingdom", recurse=True)
        self.assertIn("# Objects with tag 'loc.kingdom'", out)
        self.assertIn("loc.kingdom", out)
        self.assertIn("loc.city_a", out)
        self.assertIn("## Children of tag 'loc.city_a'", out)
        self.assertIn("loc.tavern_1", out)
        self.assertIn("loc.tavern_2", out)
        self.assertIn("## Children of tag 'loc.city_b'", out)
        self.assertIn("loc.tavern_3", out)

    def test_cli_same_type_prints_nothing(self) -> None:
        _build_part_fixture(self.store)
        out = self._run_with_tag_cli("part.head", same_type_only=True)
        self.assertEqual(out.strip(), "")

    def test_cli_same_type_recurse_prints_nothing(self) -> None:
        _build_part_fixture(self.store)
        out = self._run_with_tag_cli("part.head", recurse=True, same_type_only=True)
        self.assertEqual(out.strip(), "")

    def test_cli_recurse_follows_dot_tags_not_object_ids_as_tags(self) -> None:
        _build_part_fixture(self.store)
        out = self._run_with_tag_cli("part.head", recurse=True)
        self.assertIn("# Objects with tag 'part.head'", out)
        self.assertIn("person.amy", out)
        self.assertIn("person.carlos", out)
        self.assertIn("## Children of tag 'part.body'", out)
        self.assertNotIn("## Children of tag 'person.amy'", out)
        self.assertNotIn("## Children of tag 'person.carlos'", out)

    def test_cli_recurse_expand_prints_all_objects_by_layer(self) -> None:
        _build_map_fixture(self.store)
        out = self._run_with_tag_cli("loc.kingdom", recurse=True, expand=True)
        self.assertIn("# From tag 'loc.city_a'", out)
        self.assertIn("KB['loc.tavern_1']", out)
        self.assertIn("KB['loc.tavern_2']", out)
        self.assertIn("KB['loc.tavern_3']", out)
        self.assertIn("Tavern 1.", out)
        self.assertIn("Tavern 2.", out)
        self.assertIn("Tavern 3.", out)
