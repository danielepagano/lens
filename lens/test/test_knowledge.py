"""Unit tests for knowledge store and kb CLI."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lens.core.knowledge import KnowledgeStore, parse_id


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

    def test_copy_object_different_type(self) -> None:
        self.store.store_object("place.nyc", "NYC content")
        self.store.copy_object("place.nyc", "person.nyc")
        path = self.root / "knowledge" / "person" / "nyc.md"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "NYC content")

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

    def test_cli_copy_different_type(self) -> None:
        self._run_store("place.nyc", "NYC")
        self._run_copy("place.nyc", "person.nyc")
        path = self.root / "knowledge" / "person" / "nyc.md"
        self.assertTrue(path.exists())

    def test_cli_rename(self) -> None:
        self._run_store("place.nyc", "City")
        self._run_rename("place.nyc", "place.boston")
        self.assertFalse((self.root / "knowledge" / "place" / "nyc.md").exists())
        self.assertEqual(
            (self.root / "knowledge" / "place" / "boston.md").read_text(),
            "City",
        )

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
        out = self._run_get(["person.amy!"])
        self.assertIn("person.amy", out)
        self.assertIn("place.nyc", out)
        self.assertIn("NYC", out)
        self.assertIn("Amy", out)

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
            "tags": {"protagonist": ["person.hero"]},
            "objects": {"person.hero": ["protagonist"]},
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
        # Tags from the dataset source are inherited.
        tags = self.store.get_tags("person.hero2")
        self.assertIn("protagonist", tags)

    # --- rename_object with dataset source raises ---

    def test_rename_dataset_item_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.store.rename_object("person.hero", "person.hero_renamed")
        self.assertIn("dataset", str(ctx.exception))


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
