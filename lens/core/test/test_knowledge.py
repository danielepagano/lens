"""Unit tests for knowledge store and kb CLI."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lens.core.knowledge import KnowledgeObject, KnowledgeStore, parse_id


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


class TestKnowledgeStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)
        self.store = KnowledgeStore(self.root)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_store_with_content(self) -> None:
        self.store.store_object("place.nyc", "A big city.")
        path = self.root / "knowledge" / "place" / "nyc.md"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "A big city.")

    def test_store_no_content_creates_empty(self) -> None:
        self.store.store_object("place.NYC", None)
        path = self.root / "knowledge" / "place" / "nyc.md"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "")

    def test_store_no_content_noop_when_exists(self) -> None:
        path = self.root / "knowledge" / "place" / "nyc.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original")
        self.store.store_object("place.nyc", None)
        self.assertEqual(path.read_text(), "original")

    def test_store_use_template(self) -> None:
        self.store.set_template("place", "Template: describe the place.")
        self.store.store_object("place.nyc", None, use_template=True)
        path = self.root / "knowledge" / "place" / "nyc.md"
        self.assertEqual(path.read_text(), "Template: describe the place.")

    def test_template_declared_tags_applied_on_create(self) -> None:
        self.store.set_template(
            "tracker",
            "[\n    kb-details: true\n    tags: state\n]: #\n\nDescribe the tracker.",
        )
        self.store.store_object("tracker.combat", None, use_template=True)
        self.assertEqual(self.store.get_tags("tracker.combat"), ["state"])
        path = self.root / "knowledge" / "tracker" / "combat.md"
        body = path.read_text()
        self.assertNotIn("tags:", body)
        self.assertIn("kb-details: true", body)
        self.assertIn("Describe the tracker.", body)

    def test_template_declared_tags_list(self) -> None:
        self.store.set_template(
            "front",
            "[\n    tags:\n      - remember.core\n      - active\n]: #\n\nBody.",
        )
        self.store.store_object("front.goblins", None, use_template=True)
        self.assertEqual(
            set(self.store.get_tags("front.goblins")), {"remember.core", "active"}
        )

    def test_template_no_tags_declaration_is_noop(self) -> None:
        self.store.set_template("place", "Template: describe the place.")
        self.store.store_object("place.nyc", None, use_template=True)
        self.assertEqual(self.store.get_tags("place.nyc"), [])

    def test_template_tags_not_reapplied_after_removal(self) -> None:
        self.store.set_template(
            "tracker",
            "[\n    tags: state\n]: #\n\nDescribe the tracker.",
        )
        self.store.store_object("tracker.combat", None, use_template=True)
        self.assertEqual(self.store.get_tags("tracker.combat"), ["state"])

        self.store.remove_tags("tracker.combat", ["state"])
        self.assertEqual(self.store.get_tags("tracker.combat"), [])

        # A plain content update (no template) must not resurrect the tag.
        self.store.store_object("tracker.combat", "Updated body.")
        self.assertEqual(self.store.get_tags("tracker.combat"), [])

    def test_template_create_and_update(self) -> None:
        self.store.set_template("npc", "First template")
        self.assertEqual(self.store.get_template("NPC"), "First template")
        self.store.set_template("npc", "Updated template")
        self.assertEqual(self.store.get_template("npc"), "Updated template")

    def test_template_print_when_no_content(self) -> None:
        self.store.set_template("npc", "Template here")
        tpl = self.store.get_template("npc")
        self.assertEqual(tpl, "Template here")
        tpl_missing = self.store.get_template("nonexistent")
        self.assertIsNone(tpl_missing)

    def test_tags_add_remove(self) -> None:
        self.store.store_object("place.nyc", "City")
        self.store.add_tags("place.NYC", ["FEATURED", "kind:region"])
        self.assertEqual(
            set(self.store.get_tags("place.nyc")),
            {"featured", "kind:region"},
        )
        self.store.remove_tags("place.nyc", ["FEATURED"])
        self.assertEqual(set(self.store.get_tags("place.nyc")), {"kind:region"})

    def test_tags_persist_across_store(self) -> None:
        self.store.store_object("place.nyc", "City")
        self.store.add_tags("place.nyc", ["featured"])
        self.store.store_object("place.nyc", "Updated city")
        self.assertEqual(self.store.get_tags("place.nyc"), ["featured"])

    def test_delete_removes_file_and_tags(self) -> None:
        self.store.store_object("place.nyc", "City")
        self.store.add_tags("place.nyc", ["featured"])
        path = self.root / "knowledge" / "place" / "nyc.md"
        self.assertTrue(path.exists())
        self.store.delete_object("place.nyc")
        self.assertFalse(path.exists())
        self.assertEqual(self.store.get_tags("place.nyc"), [])

    def test_delete_removes_references(self) -> None:
        self.store.store_object("place.nyc", "City")
        self.store.store_object("person.amy", "Person")
        self.store.add_tags("person.amy", ["place.nyc", "featured"])
        self.store.delete_object("place.nyc")
        import tomllib

        with (self.root / "knowledge" / "tags.toml").open("rb") as f:
            data = tomllib.load(f)
        self.assertNotIn("place.nyc", data.get("tags", {}))
        self.assertNotIn("place.nyc", data.get("objects", {}).get("person.amy", []))
        self.assertIn("featured", data.get("objects", {}).get("person.amy", []))
        self.assertEqual(self.store.get_tags("person.amy"), ["featured"])

    def test_copy_object_same_type(self) -> None:
        self.store.store_object("place.nyc", "Big city")
        self.store.add_tags("place.nyc", ["featured"])
        self.store.copy_object("place.nyc", "place.boston")
        path = self.root / "knowledge" / "place" / "boston.md"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "Big city")
        self.assertEqual(set(self.store.get_tags("place.boston")), {"featured"})
        self.assertEqual(set(self.store.get_tags("place.nyc")), {"featured"})

    def test_copy_object_when_source_used_as_tag(self) -> None:
        """When source ID is used as a tag by others, copy adds target as that tag for them."""
        self.store.store_object("location.kingdom", "The kingdom.")
        self.store.store_object("place.city_a", "City A.")
        self.store.store_object("place.city_b", "City B.")
        self.store.add_tags("place.city_a", ["location.kingdom", "place.city_b"])
        self.store.add_tags("place.city_b", ["location.kingdom", "place.city_a"])
        self.store.copy_object("location.kingdom", "location.realm")
        self.assertEqual(set(self.store.get_tags("place.city_a")), {"location.kingdom", "location.realm", "place.city_b"})
        self.assertEqual(set(self.store.get_tags("place.city_b")), {"location.kingdom", "location.realm", "place.city_a"})

    def test_copy_object_different_type(self) -> None:
        self.store.store_object("place.nyc", "NYC content")
        self.store.add_tags("place.nyc", ["featured", "kind:city"])
        self.store.copy_object("place.nyc", "person.nyc")
        path = self.root / "knowledge" / "person" / "nyc.md"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "NYC content")
        self.assertEqual(set(self.store.get_tags("person.nyc")), {"featured", "kind:city"})

    def test_copy_object_tag_index_preserved(self) -> None:
        """Verify tags.toml tag_to_objs and obj_to_tags stay in sync after copy."""
        import tomllib

        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        self.store.add_tags("place.nyc", ["featured", "kind:city"])
        self.store.add_tags("place.boston", ["featured"])
        self.store.copy_object("place.nyc", "place.la")
        with (self.root / "knowledge" / "tags.toml").open("rb") as f:
            data = tomllib.load(f)
        tags_map = data.get("tags", {})
        objs_map = data.get("objects", {})
        self.assertIn("place.nyc", tags_map.get("featured", []))
        self.assertIn("place.boston", tags_map.get("featured", []))
        self.assertIn("place.la", tags_map.get("featured", []))
        self.assertIn("place.nyc", tags_map.get("kind:city", []))
        self.assertIn("place.la", tags_map.get("kind:city", []))
        self.assertEqual(set(objs_map.get("place.nyc", [])), {"featured", "kind:city"})
        self.assertEqual(set(objs_map.get("place.la", [])), {"featured", "kind:city"})

    def test_copy_object_target_exists_raises(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        with self.assertRaises(ValueError) as ctx:
            self.store.copy_object("place.nyc", "place.boston")
        self.assertIn("already exists", str(ctx.exception))

    def test_copy_object_source_missing_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.store.copy_object("place.missing", "place.new")
        self.assertIn("does not exist", str(ctx.exception))

    def test_rename_object_same_type(self) -> None:
        self.store.store_object("place.nyc", "Big city")
        self.store.add_tags("place.nyc", ["featured"])
        self.store.rename_object("place.nyc", "place.boston")
        self.assertFalse((self.root / "knowledge" / "place" / "nyc.md").exists())
        path = self.root / "knowledge" / "place" / "boston.md"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "Big city")
        self.assertEqual(set(self.store.get_tags("place.boston")), {"featured"})
        self.assertEqual(self.store.get_tags("place.nyc"), [])

    def test_rename_object_different_type(self) -> None:
        self.store.store_object("place.nyc", "NYC content")
        self.store.add_tags("place.nyc", ["featured"])
        self.store.rename_object("place.nyc", "person.nyc")
        self.assertFalse((self.root / "knowledge" / "place" / "nyc.md").exists())
        path = self.root / "knowledge" / "person" / "nyc.md"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "NYC content")
        self.assertEqual(set(self.store.get_tags("person.nyc")), {"featured"})

    def test_rename_object_target_exists_raises(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        with self.assertRaises(ValueError) as ctx:
            self.store.rename_object("place.nyc", "place.boston")
        self.assertIn("already exists", str(ctx.exception))

    def test_rename_object_source_missing_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.store.rename_object("place.missing", "place.new")
        self.assertIn("does not exist", str(ctx.exception))

    def test_rename_object_tag_index_preserved(self) -> None:
        """Verify tags.toml tag_to_objs and obj_to_tags stay in sync after rename."""
        import tomllib

        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("place.boston", "Boston")
        self.store.add_tags("place.nyc", ["featured", "kind:city"])
        self.store.add_tags("place.boston", ["featured"])
        self.store.rename_object("place.nyc", "place.manhattan")
        with (self.root / "knowledge" / "tags.toml").open("rb") as f:
            data = tomllib.load(f)
        tags_map = data.get("tags", {})
        objs_map = data.get("objects", {})
        self.assertNotIn("place.nyc", tags_map.get("featured", []))
        self.assertIn("place.boston", tags_map.get("featured", []))
        self.assertIn("place.manhattan", tags_map.get("featured", []))
        self.assertNotIn("place.nyc", tags_map.get("kind:city", []))
        self.assertIn("place.manhattan", tags_map.get("kind:city", []))
        self.assertNotIn("place.nyc", objs_map)
        self.assertEqual(set(objs_map.get("place.manhattan", [])), {"featured", "kind:city"})

    def test_rename_object_dot_tag_updated(self) -> None:
        """When object ID is used as a dot-tag by others, rename updates all references."""
        self.store.store_object("location.kingdom", "The kingdom.")
        self.store.store_object("location.city_a", "City A.")
        self.store.store_object("location.city_b", "City B.")
        self.store.add_tags("location.city_a", ["location.kingdom"])
        self.store.add_tags("location.city_b", ["location.kingdom"])
        self.store.rename_object("location.kingdom", "location.realm")
        self.assertEqual(set(self.store.get_tags("location.city_a")), {"location.realm"})
        self.assertEqual(set(self.store.get_tags("location.city_b")), {"location.realm"})
        self.assertEqual(self.store.get_ids_with_tag("location.realm"), ["location.city_a", "location.city_b"])
        self.assertEqual(self.store.get_ids_with_tag("location.kingdom"), [])

    def test_copy_object_leaves_changes_unstaged(self) -> None:
        """Copy must not stage its changes (single Storage for whole op)."""
        self.store.store_object("place.nyc", "NYC")
        self.store.add_tags("place.nyc", ["featured"])
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=self.root, capture_output=True, check=True)
        self.store.copy_object("place.nyc", "place.boston")
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertIn("knowledge/place/boston.md", r.stdout)
        self.assertIn("knowledge/tags.toml", r.stdout)
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertNotIn("boston.md", r.stdout)

    def test_delete_removes_references_tags_only_file(self) -> None:
        self.store.store_object("note.one", "one")
        self.store.store_object("note.two", "two")
        self.store.add_tags("note.one", ["good", "note.two"])
        import tomllib

        with (self.root / "knowledge" / "tags.toml").open("rb") as f:
            data = tomllib.load(f)
        tags_only = {"tags": data["tags"]}
        with (self.root / "knowledge" / "tags.toml").open("wb") as f:
            import tomli_w

            tomli_w.dump(tags_only, f)
        self.store.delete_object("note.two")
        self.assertEqual(self.store.get_tags("note.one"), ["good"])

    def test_tags_store_canonical_ids(self) -> None:
        self.store.store_object("note.one", "Content")
        self.store.add_tags("note.one", ["good"])
        import tomllib

        with (self.root / "knowledge" / "tags.toml").open("rb") as f:
            data = tomllib.load(f)
        self.assertIn("note.one", data.get("tags", {}).get("good", []))
        self.assertIn("note.one", data.get("objects", {}))
        self.assertEqual(data.get("objects", {}).get("note.one", []), ["good"])

    def test_list_unique_tags_no_filter_returns_all_tags(self) -> None:
        self.store.store_object("stat.ghoul", "Ghoul")
        self.store.store_object("stat.wight", "Wight")
        self.store.add_tags("stat.ghoul", ["cr:1", "type:undead", "habitat:any"])
        self.store.add_tags("stat.wight", ["cr:3", "type:undead", "habitat:any"])
        tags = self.store.list_unique_tags()
        self.assertEqual(sorted(tags), ["cr:1", "cr:3", "habitat:any", "type:undead"])

    def test_list_unique_tags_type_filter(self) -> None:
        self.store.store_object("stat.ghoul", "Ghoul")
        self.store.store_object("spell.fireball", "Fireball")
        self.store.add_tags("stat.ghoul", ["cr:1", "type:undead"])
        self.store.add_tags("spell.fireball", ["level:3", "type:evocation"])
        tags = self.store.list_unique_tags(type_filter="stat")
        self.assertEqual(sorted(tags), ["cr:1", "type:undead"])

    def test_list_unique_tags_prefix_filter(self) -> None:
        self.store.store_object("stat.ghoul", "Ghoul")
        self.store.add_tags("stat.ghoul", ["cr:1", "type:undead", "habitat:any"])
        tags = self.store.list_unique_tags(prefix_filter="cr:")
        self.assertEqual(tags, ["cr:1"])

    def test_list_unique_tags_combined_filters(self) -> None:
        self.store.store_object("stat.ghoul", "Ghoul")
        self.store.store_object("stat.wight", "Wight")
        self.store.add_tags("stat.ghoul", ["cr:1", "type:undead"])
        self.store.add_tags("stat.wight", ["cr:3", "type:undead"])
        tags = self.store.list_unique_tags(type_filter="stat", prefix_filter="cr:")
        self.assertEqual(sorted(tags), ["cr:1", "cr:3"])

    def test_get_single(self) -> None:
        self.store.store_object("place.nyc", "City content")
        objs = self.store.get_objects(["place.nyc"])
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs["place.nyc"].text, "City content")

    def test_get_multiple(self) -> None:
        self.store.store_object("place.nyc", "City")
        self.store.store_object("place.boston", "Boston")
        objs = self.store.get_objects(["place.nyc", "place.boston"])
        self.assertEqual(len(objs), 2)
        self.assertIn("place.nyc", objs)
        self.assertIn("place.boston", objs)

    def test_get_linked_objects(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("person.amy", "Amy")
        self.store.add_tags("person.amy", ["place.nyc"])
        objs = self.store.get_objects(
            ["person.amy"],
            expand_linked_for={"person.amy"},
        )
        self.assertEqual(len(objs), 2)
        self.assertIn("place.nyc", objs)
        self.assertIn("person.amy", objs)

    def test_get_objects_with_links_returns_ordered_ids(self) -> None:
        """ordered_ids is deterministic: explicit first, then linked in discovery order."""
        self.store.store_object("place.market", "The market")
        self.store.store_object("person.amy", "Amy")
        self.store.add_tags("person.amy", ["place.market"])
        ordered_ids, objects = self.store.get_objects_with_links(["person.amy+"])
        self.assertEqual(ordered_ids, ["person.amy", "place.market"])
        self.assertEqual(len(objects), 2)
        for cid in ordered_ids:
            self.assertIn(cid, objects)

    def test_get_objects_with_links_onehop_does_not_recurse(self) -> None:
        self.store.store_object("note.root", "Root")
        self.store.store_object("note.mid", "Mid")
        self.store.store_object("note.leaf", "Leaf")
        self.store.add_tags("note.root", ["note.mid"])
        self.store.add_tags("note.mid", ["note.leaf"])

        ordered_ids, objects = self.store.get_objects_with_links(["note.root+"])

        self.assertEqual(ordered_ids, ["note.root", "note.mid"])
        self.assertIn("note.root", objects)
        self.assertIn("note.mid", objects)
        self.assertNotIn("note.leaf", objects)

    def test_get_objects_with_links_recursive_bfs_linear(self) -> None:
        self.store.store_object("note.root", "Root")
        self.store.store_object("note.mid", "Mid")
        self.store.store_object("note.leaf", "Leaf")
        self.store.add_tags("note.root", ["note.mid"])
        self.store.add_tags("note.mid", ["note.leaf"])

        ordered_ids, objects = self.store.get_objects_with_links(["note.root++"])

        self.assertEqual(ordered_ids, ["note.root", "note.mid", "note.leaf"])
        for cid in ordered_ids:
            self.assertIn(cid, objects)

    def test_get_objects_with_links_recursive_bfs_branching(self) -> None:
        self.store.store_object("note.root", "Root")
        self.store.store_object("note.a", "A")
        self.store.store_object("note.b", "B")
        self.store.store_object("note.c", "C")
        self.store.store_object("note.d", "D")
        self.store.add_tags("note.root", ["note.b", "note.a"])
        self.store.add_tags("note.a", ["note.c"])
        self.store.add_tags("note.b", ["note.d"])

        ordered_ids, _ = self.store.get_objects_with_links(["note.root++"])

        self.assertEqual(ordered_ids, ["note.root", "note.a", "note.b", "note.c", "note.d"])

    def test_get_objects_with_links_recursive_bfs_cycle_safe(self) -> None:
        self.store.store_object("note.a", "A")
        self.store.store_object("note.b", "B")
        self.store.store_object("note.c", "C")
        self.store.add_tags("note.a", ["note.b"])
        self.store.add_tags("note.b", ["note.c"])
        self.store.add_tags("note.c", ["note.a"])

        ordered_ids, objects = self.store.get_objects_with_links(["note.a++"])

        self.assertEqual(ordered_ids, ["note.a", "note.b", "note.c"])
        self.assertEqual(len(set(ordered_ids)), 3)
        for cid in ordered_ids:
            self.assertIn(cid, objects)

    def test_get_objects_with_links_recursive_and_onehop_dedup(self) -> None:
        self.store.store_object("note.root", "Root")
        self.store.store_object("note.mid", "Mid")
        self.store.store_object("note.leaf", "Leaf")
        self.store.store_object("note.other", "Other")
        self.store.add_tags("note.root", ["note.mid"])
        self.store.add_tags("note.mid", ["note.leaf"])
        self.store.add_tags("note.other", ["note.leaf"])

        ordered_ids, objects = self.store.get_objects_with_links(["note.root++", "note.other+"])

        self.assertEqual(set(ordered_ids), {"note.root", "note.other", "note.mid", "note.leaf"})
        self.assertEqual(len(ordered_ids), len(set(ordered_ids)))
        for cid in ordered_ids:
            self.assertIn(cid, objects)

    def test_get_invalid_dot_tags(self) -> None:
        self.store.store_object("person.amy", "Amy")
        self.store.add_tags("person.amy", ["place.nyc", "featured"])
        invalid = self.store.get_invalid_dot_tags(["place.nyc", "featured"])
        self.assertEqual(invalid, ["place.nyc"])
        self.store.store_object("place.nyc", "NYC")
        invalid_after = self.store.get_invalid_dot_tags(["place.nyc", "featured"])
        self.assertEqual(invalid_after, [])

    def test_get_strips_comments_by_default(self) -> None:
        self.store.store_object("place.nyc", "Visible\n[ hidden ]: #\nMore")
        objs = self.store.get_objects(["place.nyc"])
        self.assertEqual(objs["place.nyc"].text, "Visible\n[ hidden ]: #\nMore")
        from lens.core.annotations import strip_markdown_comments

        stripped = strip_markdown_comments(objs["place.nyc"].text)
        self.assertNotIn("[ hidden ]", stripped)


class TestKbCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_extract(self, path: str) -> str:
        from io import StringIO
        import sys
        from unittest.mock import patch as _patch

        with _patch("lens.core.commands.kb.find_project_root", return_value=self.root):
            from lens.cli.commands.kb import extract

            old_stdout, old_stderr = sys.stdout, sys.stderr
            try:
                out_buf, err_buf = StringIO(), StringIO()
                sys.stdout, sys.stderr = out_buf, err_buf
                extract(path)
                return out_buf.getvalue() + err_buf.getvalue()
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr

    def _run_store(self, id: str, content: str | None = None, use_template: bool = False) -> None:
        with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
            from lens.cli.commands.kb import add

            add(id, content, use_template)

    def _run_template(self, type_name: str, content: str | None = None) -> str | None:
        with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
            from lens.cli.commands.kb import template
            from io import StringIO
            import sys

            if content is not None:
                template(type_name, content)
                return None
            old = sys.stdout
            try:
                buf = StringIO()
                sys.stdout = buf
                template(type_name, None)
                return buf.getvalue() or None
            finally:
                sys.stdout = old

    def _run_tags(
        self,
        id: str,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> str:
        out, _ = self._run_tags_capture_stderr(id, add, remove)
        return out

    def _run_tags_capture_stderr(
        self,
        id: str,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> tuple[str, str]:
        with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
            from lens.cli.commands.kb import tag
            from io import StringIO
            import sys

            old_stdout, old_stderr = sys.stdout, sys.stderr
            try:
                out_buf, err_buf = StringIO(), StringIO()
                sys.stdout, sys.stderr = out_buf, err_buf
                tag(id, add or [], remove or [])
                return out_buf.getvalue(), err_buf.getvalue()
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr

    def _run_delete(self, id: str) -> None:
        with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
            from lens.cli.commands.kb import delete

            delete(id)

    def _run_copy(self, source_id: str, target_id: str) -> None:
        with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
            from lens.cli.commands.kb import copy

            copy(source_id, target_id)

    def _run_rename(self, old_id: str, new_id: str) -> None:
        with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
            from lens.cli.commands.kb import rename

            rename(old_id, new_id)

    def _run_get(self, ids: list[str], include_comments: bool = False) -> str:
        with patch("lens.core.commands.kb.find_project_root", return_value=self.root):
            from lens.cli.commands.kb import get
            from io import StringIO
            import sys

            old = sys.stdout
            try:
                buf = StringIO()
                sys.stdout = buf
                get(ids, include_comments)
                return buf.getvalue()
            finally:
                sys.stdout = old

    def test_cli_store(self) -> None:
        self._run_store("place.nyc", "City")
        self.assertEqual(
            (self.root / "knowledge" / "place" / "nyc.md").read_text(),
            "City",
        )

    def test_cli_template(self) -> None:
        self._run_template("npc", "NPC template")
        out = self._run_template("npc", None)
        self.assertEqual(out, "NPC template\n")

    def test_cli_tags(self) -> None:
        self._run_store("place.nyc", "City")
        out = self._run_tags("place.nyc", add=["featured"])
        self.assertEqual(out.strip(), "featured")
        out = self._run_tags("place.nyc", add=["kind:region"])
        self.assertIn("featured", out)
        self.assertIn("kind:region", out)
        out = self._run_tags("place.nyc", remove=["featured"])
        self.assertEqual(out.strip(), "kind:region")

    def test_cli_delete(self) -> None:
        self._run_store("place.nyc", "City")
        self._run_tags("place.nyc", add=["featured"])
        self._run_delete("place.nyc")
        self.assertFalse((self.root / "knowledge" / "place" / "nyc.md").exists())

    def test_cli_copy(self) -> None:
        self._run_store("place.nyc", "City content")
        self._run_tags("place.nyc", add=["featured"])
        self._run_copy("place.nyc", "place.boston")
        path = self.root / "knowledge" / "place" / "boston.md"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "City content")
        store = KnowledgeStore.for_project(self.root)
        self.assertEqual(set(store.get_tags("place.boston")), {"featured"})

    def test_cli_copy_different_type(self) -> None:
        self._run_store("place.nyc", "NYC")
        self._run_tags("place.nyc", add=["featured"])
        self._run_copy("place.nyc", "person.nyc")
        path = self.root / "knowledge" / "person" / "nyc.md"
        self.assertTrue(path.exists())
        store = KnowledgeStore.for_project(self.root)
        self.assertEqual(set(store.get_tags("person.nyc")), {"featured"})

    def test_cli_rename(self) -> None:
        self._run_store("place.nyc", "City")
        self._run_tags("place.nyc", add=["featured"])
        self._run_rename("place.nyc", "place.boston")
        self.assertFalse((self.root / "knowledge" / "place" / "nyc.md").exists())
        self.assertEqual(
            (self.root / "knowledge" / "place" / "boston.md").read_text(),
            "City",
        )
        store = KnowledgeStore.for_project(self.root)
        self.assertEqual(set(store.get_tags("place.boston")), {"featured"})

    def test_cli_rename_different_type(self) -> None:
        self._run_store("place.nyc", "NYC")
        self._run_rename("place.nyc", "person.nyc")
        self.assertFalse((self.root / "knowledge" / "place" / "nyc.md").exists())
        self.assertEqual(
            (self.root / "knowledge" / "person" / "nyc.md").read_text(),
            "NYC",
        )

    def test_cli_get(self) -> None:
        self._run_store("place.nyc", "City")
        self._run_store("place.boston", "Boston")
        out = self._run_get(["place.nyc", "place.boston"])
        self.assertIn("place.nyc", out)
        self.assertIn("place.boston", out)
        self.assertIn("City", out)
        self.assertIn("Boston", out)

    def test_cli_get_prints_tags(self) -> None:
        self._run_store("place.nyc", "City")
        self._run_tags("place.nyc", add=["featured", "kind:region"])
        out = self._run_get(["place.nyc"])
        self.assertIn("TAGS=featured, kind:region", out)

    def test_cli_get_strips_comments(self) -> None:
        self._run_store("place.nyc", "Visible\n[ comment ]: #\nMore")
        out = self._run_get(["place.nyc"])
        self.assertIn("Visible", out)
        self.assertIn("More", out)
        self.assertNotIn("[ comment ]", out)

    def test_cli_get_include_comments(self) -> None:
        self._run_store("place.nyc", "Visible\n[ comment ]: #\nMore")
        out = self._run_get(["place.nyc"], include_comments=True)
        self.assertIn("[ comment ]", out)

    def test_cli_get_linked_objects(self) -> None:
        self._run_store("place.nyc", "NYC")
        self._run_store("person.amy", "Amy")
        self._run_tags("person.amy", add=["place.nyc"])
        out = self._run_get(["person.amy+"])
        self.assertIn("person.amy", out)
        self.assertIn("place.nyc", out)
        self.assertIn("NYC", out)
        self.assertIn("Amy", out)

    def test_cli_get_recursive_linked_objects(self) -> None:
        self._run_store("note.root", "Root")
        self._run_store("note.mid", "Mid")
        self._run_store("note.leaf", "Leaf")
        self._run_tags("note.root", add=["note.mid"])
        self._run_tags("note.mid", add=["note.leaf"])

        out = self._run_get(["note.root++"])

        self.assertIn("KB['note.root']", out)
        self.assertIn("KB['note.mid']", out)
        self.assertIn("KB['note.leaf']", out)
        self.assertEqual(out.count("KB['note.root']"), 1)
        self.assertEqual(out.count("KB['note.mid']"), 1)
        self.assertEqual(out.count("KB['note.leaf']"), 1)

    def test_cli_get_recursive_cycle_prints_once(self) -> None:
        self._run_store("note.a", "A")
        self._run_store("note.b", "B")
        self._run_store("note.c", "C")
        self._run_tags("note.a", add=["note.b"])
        self._run_tags("note.b", add=["note.c"])
        self._run_tags("note.c", add=["note.a"])

        out = self._run_get(["note.a++"])

        self.assertEqual(out.count("KB['note.a']"), 1)
        self.assertEqual(out.count("KB['note.b']"), 1)
        self.assertEqual(out.count("KB['note.c']"), 1)

    def test_cli_get_invalid_dot_tag_warning(self) -> None:
        self._run_store("person.amy", "Amy")
        self._run_tags("person.amy", add=["place.nonexistent"])
        out = self._run_get(["person.amy"])
        self.assertIn("TAGS=place.nonexistent", out)
        self.assertIn("invalid dot-tag", out)
        self.assertIn("place.nonexistent", out)

    def test_cli_tags_invalid_dot_tag_warning(self) -> None:
        self._run_store("person.amy", "Amy")
        out, err = self._run_tags_capture_stderr("person.amy", add=["place.nonexistent"])
        self.assertIn("place.nonexistent", out)
        self.assertIn("invalid dot-tag", err)
        self.assertIn("place.nonexistent", err)

    def test_cli_shows_help_when_required_params_missing(self) -> None:
        result = subprocess.run(
            ["python", "-m", "lens.cli.main", "kb", "add"],
            capture_output=True,
            text=True,
            cwd=self.root,
        )
        self.assertIn("Usage", result.stdout + result.stderr)
        self.assertIn("ID", result.stdout + result.stderr)

    def test_cli_extract_directory_multi_file_single_transaction(self) -> None:
        # Build nested directory with multiple .md files
        sub = self.root / "notes" / "chapter1"
        sub.mkdir(parents=True, exist_ok=True)
        top_file = self.root / "notes" / "top.md"
        top_file.write_text(
            """\
```kb
---
id: person.alice
---
Alice.
```""",
            encoding="utf-8",
        )
        sub_file = sub / "child.md"
        sub_file.write_text(
            """\
```kb
---
id: person.bob
---
Bob.
```""",
            encoding="utf-8",
        )

        out = self._run_extract(str(self.root / "notes"))
        self.assertIn("Inserted:", out)

        # At least some writes should be pending in a single transaction
        r = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        all_pending = r.stdout.strip() + "\n" + untracked.stdout.strip()
        self.assertTrue("alice.md" in all_pending or "bob.md" in all_pending)

    def test_cli_extract_directory_duplicate_id_cumulative_tags(self) -> None:
        base = self.root / "notes2"
        left = base / "a"
        right = base / "b"
        left.mkdir(parents=True, exist_ok=True)
        right.mkdir(parents=True, exist_ok=True)

        # Lexicographical directory order: "a" then "b"; within each,
        # files are sorted by name.
        (left / "hero.md").write_text(
            """\
```kb
---
id: npc.hero
tags:
  - first-tag
---
First version.
```""",
            encoding="utf-8",
        )
        (right / "hero.md").write_text(
            """\
```kb
---
id: npc.hero
tags:
  - second-tag
---
Second version.
```""",
            encoding="utf-8",
        )

        self._run_extract(str(base))

        obj_path = self.root / "knowledge" / "npc" / "hero.md"
        self.assertTrue(obj_path.exists())
        self.assertEqual(obj_path.read_text(), "Second version.")
        store = KnowledgeStore.for_project(self.root)
        tags = store.get_tags("npc.hero")
        self.assertIn("first-tag", tags)
        self.assertIn("second-tag", tags)


class TestKnowledgeDatasets(unittest.TestCase):
    """Unit tests for KB dataset support (lookup fallback, copy-on-write, etc.)."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.project = Path(self.tmp) / "project"
        self.dataset = Path(self.tmp) / "dataset"
        self.project.mkdir()
        self.dataset.mkdir()
        _make_project(self.project)
        # Build a minimal dataset (no git, no Storage needed — read-only).
        (self.dataset / "knowledge").mkdir()
        (self.dataset / "knowledge" / "person").mkdir()
        (self.dataset / "knowledge" / "place").mkdir()
        (self.dataset / "knowledge" / "person" / "hero.md").write_text("The hero.")
        (self.dataset / "knowledge" / "place" / "keep.md").write_text("A fortified keep.")
        import io as _io
        import tomli_w as _tomli_w
        tags: dict[str, object] = {
            "tags": {"place.dungeon": ["person.hero"], "protagonist": ["person.hero"]},
            "objects": {"person.hero": ["place.dungeon", "protagonist"]},
        }
        buf = _io.BytesIO()
        _tomli_w.dump(tags, buf)
        (self.dataset / "knowledge" / "tags.toml").write_bytes(buf.getvalue())

        ds_store = KnowledgeStore(self.dataset)
        self.store = KnowledgeStore(self.project, dataset_stores=[ds_store])

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- Lookup / fallback ---

    def test_dataset_item_visible(self) -> None:
        obj = self.store.get_objects(["person.hero"]).get("person.hero")
        self.assertIsNotNone(obj)
        assert obj is not None
        self.assertEqual(obj.text, "The hero.")

    def test_project_item_visible(self) -> None:
        self.store.store_object("note.one", "Note content.")
        obj = self.store.get_objects(["note.one"]).get("note.one")
        self.assertIsNotNone(obj)
        assert obj is not None
        self.assertEqual(obj.text, "Note content.")

    def test_project_shadows_dataset(self) -> None:
        self.store.store_object("person.hero", "Overridden hero.")
        obj = self.store.get_objects(["person.hero"]).get("person.hero")
        self.assertIsNotNone(obj)
        assert obj is not None
        self.assertEqual(obj.text, "Overridden hero.")

    def test_dataset_tags_visible(self) -> None:
        # Tags on a dataset-only item come through the dataset store's get_tags.
        objs = self.store.get_objects(["person.hero"])
        obj = objs.get("person.hero")
        self.assertIsNotNone(obj)
        assert obj is not None
        self.assertIn("protagonist", obj.tags)

    def test_store_object_none_treats_dataset_item_as_existing(self) -> None:
        """store_object(id, None) should be a no-op if the item is in a dataset."""
        self.store.store_object("person.hero", None)
        hero_path = self.project / "knowledge" / "person" / "hero.md"
        self.assertFalse(hero_path.exists(), "dataset item should not be copied on no-content store")

    # --- Copy-on-write ---

    def test_add_tags_triggers_copy_on_write(self) -> None:
        err = self.store.add_tags("person.hero", ["featured"])
        self.assertIsNone(err)
        hero_path = self.project / "knowledge" / "person" / "hero.md"
        self.assertTrue(hero_path.exists())
        self.assertEqual(hero_path.read_text(), "The hero.")
        tags = self.store.get_tags("person.hero")
        self.assertIn("featured", tags)
        # Original dataset tags should be preserved in the project copy.
        self.assertIn("protagonist", tags)

    def test_remove_tags_triggers_copy_on_write(self) -> None:
        # First make the item visible via copy-on-write via add_tags.
        self.store.add_tags("person.hero", ["featured"])
        # Now remove a tag.
        self.store.remove_tags("person.hero", ["featured"])
        tags = self.store.get_tags("person.hero")
        self.assertNotIn("featured", tags)

    # --- Delete semantics ---

    def test_delete_dataset_only_is_noop(self) -> None:
        keep_path = self.project / "knowledge" / "place" / "keep.md"
        self.assertFalse(keep_path.exists())
        self.store.delete_object("place.keep")
        self.assertFalse(keep_path.exists())
        # Still visible from dataset.
        obj = self.store.get_objects(["place.keep"]).get("place.keep")
        self.assertIsNotNone(obj)

    def test_delete_local_item_works(self) -> None:
        self.store.store_object("note.tmp", "Temporary.")
        tmp_path = self.project / "knowledge" / "note" / "tmp.md"
        self.assertTrue(tmp_path.exists())
        self.store.delete_object("note.tmp")
        self.assertFalse(tmp_path.exists())

    # --- copy_object with dataset source ---

    def test_copy_from_dataset_to_project(self) -> None:
        self.store.copy_object("person.hero", "person.hero2")
        hero2_path = self.project / "knowledge" / "person" / "hero2.md"
        self.assertTrue(hero2_path.exists())
        self.assertEqual(hero2_path.read_text(), "The hero.")
        tags = self.store.get_tags("person.hero2")
        self.assertEqual(set(tags), {"place.dungeon", "protagonist"})

    # --- rename_object with dataset source raises ---

    def test_rename_dataset_item_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.store.rename_object("person.hero", "person.hero_renamed")
        self.assertIn("dataset", str(ctx.exception))


class TestKnowledgeObjectFormatStripHtml(unittest.TestCase):
    def test_strip_html_comments_single_line(self) -> None:
        obj = KnowledgeObject(
            type="spell",
            id="spell.foo",
            text="Hello <!-- hidden --> world",
            tags=[],
        )
        out = obj.format(strip_html_comments=True)
        self.assertIn("Hello", out)
        self.assertIn("world", out)
        self.assertNotIn("hidden", out)
        self.assertNotIn("<!--", out)

    def test_strip_html_comments_multiline(self) -> None:
        obj = KnowledgeObject(
            type="spell",
            id="spell.bar",
            text="Line1\n<!-- ai:secret:\nrot13\n-->\nLine2",
            tags=["arcane"],
        )
        out = obj.format(strip_html_comments=True)
        self.assertIn("Line1", out)
        self.assertIn("Line2", out)
        self.assertNotIn("rot13", out)
        self.assertNotIn("-->", out)

    def test_default_keeps_html_comments(self) -> None:
        obj = KnowledgeObject(
            type="note",
            id="note.x",
            text="See <!-- tip --> here",
            tags=[],
        )
        out = obj.format()
        self.assertIn("<!-- tip -->", out)


class TestKnowledgeObjectFormatVerbatim(unittest.TestCase):
    """format() must not indent, wrap or transform body lines.

    These tests guard the contract that tools like kb_patch rely on:
    every body line the LLM sees in a prompt must be byte-identical to a
    line it can quote back as a ``target`` selector.
    """

    def test_header_is_kb_id_only_when_no_tags(self) -> None:
        obj = KnowledgeObject(type="person", id="person.amy", text="Amy.\n")
        out = obj.format()
        self.assertEqual(out, "KB['person.amy']\nAmy.\n")

    def test_tags_appear_on_header_line(self) -> None:
        obj = KnowledgeObject(
            type="person",
            id="person.amy",
            text="Amy.\n",
            tags=["baker", "nyc"],
        )
        out = obj.format()
        first_line = out.split("\n", 1)[0]
        self.assertTrue(first_line.startswith("KB['person.amy']"))
        self.assertIn("TAGS=baker, nyc", first_line)

    def test_body_lines_are_flush_left(self) -> None:
        obj = KnowledgeObject(
            type="note",
            id="note.x",
            text="line one\nline two\nline three\n",
        )
        out = obj.format()
        # Every body line must appear exactly as stored — no leading indent.
        self.assertIn("\nline one\n", out)
        self.assertIn("\nline two\n", out)
        self.assertIn("\nline three\n", out)
        # And none of them should be prefixed with indentation.
        for body_line in ("  line one", "  line two", "  line three"):
            self.assertNotIn(body_line, out)

    def test_leading_whitespace_is_preserved(self) -> None:
        """A body line that legitimately starts with spaces must round-trip."""
        obj = KnowledgeObject(
            type="note",
            id="note.y",
            text="  indented body\nflush\n",
        )
        out = obj.format()
        # The user's leading two spaces survive; our formatter adds nothing.
        self.assertIn("\n  indented body\n", out)
        # And the flush line is flush — no accidental indent applied.
        self.assertIn("\nflush\n", out)

    def test_blank_body_line_is_preserved(self) -> None:
        obj = KnowledgeObject(
            type="note",
            id="note.z",
            text="before\n\nafter\n",
        )
        out = obj.format()
        self.assertIn("before\n\nafter", out)

    def test_empty_body_produces_header_only(self) -> None:
        obj = KnowledgeObject(type="note", id="note.empty", text="")
        out = obj.format()
        self.assertEqual(out, "KB['note.empty']\n")

    def test_body_lines_survive_joined_knowledge_block(self) -> None:
        """Simulates how multiple KB entries reach the LLM prompt.

        Each body line must still be present verbatim after joining with
        ``"\\n\\n"`` (the shape used by context assembly).
        """
        a = KnowledgeObject(type="person", id="person.amy", text="Amy bakes bread.\n")
        b = KnowledgeObject(
            type="place",
            id="place.nyc",
            text="Rainy today.\nBusy port.\n",
            tags=["city"],
        )
        joined = "\n\n".join([a.format(), b.format()])
        self.assertIn("\nAmy bakes bread.\n", joined)
        self.assertIn("\nRainy today.\n", joined)
        self.assertIn("\nBusy port.\n", joined)

    def test_body_line_is_kb_patch_echoable(self) -> None:
        """An LLM reading the formatted output should be able to echo a body
        line verbatim as a kb_patch selector target and resolve it."""
        from lens.core.text_select import LineSelector, Patch, Selection, apply_patch
        obj = KnowledgeObject(
            type="person",
            id="person.amy",
            text="Amy is a baker.\nLives in NYC.\n",
        )
        formatted = obj.format()
        # Pull a body line out of the formatted output exactly as a model would.
        body_line = "Amy is a baker."
        self.assertIn(f"\n{body_line}\n", formatted)
        # And now use that same line (unchanged) as a patch target against the
        # stored text — it must resolve cleanly.
        patched = apply_patch(
            obj.text,
            Patch(
                selection=Selection(start=LineSelector(target=body_line)),
                content="Amy is a novelist.",
            ),
        )
        self.assertEqual(patched, "Amy is a novelist.\nLives in NYC.\n")


class TestParseId(unittest.TestCase):
    def test_valid_id(self) -> None:
        t, k = parse_id("place.nyc")
        self.assertEqual((t, k), ("place", "nyc"))

    def test_valid_id_multi_dot(self) -> None:
        t, k = parse_id("place.new.york")
        self.assertEqual((t, k), ("place", "new.york"))

    def test_valid_id_underscore(self) -> None:
        t, k = parse_id("place.new_york")
        self.assertEqual((t, k), ("place", "new_york"))

    def test_valid_id_normalize_case(self) -> None:
        t, k = parse_id("place.NYC")
        self.assertEqual((t, k), ("place", "nyc"))

    def test_invalid_id(self) -> None:
        with self.assertRaises(ValueError):
            parse_id("invalid")
