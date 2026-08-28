"""Where a KB object came from: project tree, dataset tree, and what lost.

The merge is invisible on disk — a dataset lives outside the project entirely —
so these tests pin the one place that can answer "is this text mine, and is
editing it a fork". They also pin what must *not* change: the crawl renders KB
objects without a source, because during generation which tree a sentence was
stored in is not part of what is true in the world.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.commands.kb import kb_object_payload, kb_source_payload
from lens.core.knowledge import KbSource, KnowledgeObject, KnowledgeStore


def _make_project(tmp: Path, datasets: list[str] | None = None) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    body = "[project]\n"
    if datasets:
        listed = ", ".join(f'"{name}"' for name in datasets)
        body += f"datasets = [{listed}]\n"
    (tmp / "lens.toml").write_text(body)
    (tmp / "knowledge").mkdir()
    (tmp / "knowledge" / "tags.toml").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True
    )


class _ProjectCase(unittest.TestCase):
    datasets: list[str] = []

    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root, self.datasets)
        self.store = KnowledgeStore.for_project(self.root)

    def tearDown(self) -> None:
        import shutil

        KnowledgeStore.clear_registry()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestDescribeSource(_ProjectCase):
    """One dataset selected, so every precedence case has a witness."""

    datasets = ["testing"]

    def test_a_project_object_reports_the_project(self) -> None:
        self.store.store_object("place.nyc", "NYC")

        source = self.store.describe_source("place.nyc")

        self.assertEqual(source, KbSource(kind="project"))
        self.assertEqual((source or KbSource("project")).label, "project")

    def test_a_dataset_object_names_the_dataset_it_came_from(self) -> None:
        """The name matters: a path would not tell a reader which dataset it is."""
        source = self.store.describe_source("person.hero")

        self.assertEqual(source, KbSource(kind="dataset", dataset="testing"))
        self.assertEqual((source or KbSource("project")).label, "dataset:testing")

    def test_a_project_copy_says_what_it_overrides(self) -> None:
        """Copy-on-write is the whole reason to ask; a fork must announce itself."""
        self.store.store_object("person.hero", "My own hero.")

        source = self.store.describe_source("person.hero")

        self.assertEqual(source, KbSource(kind="project", shadows=("testing",)))
        self.assertEqual(
            (source or KbSource("project")).label, "project (shadows dataset:testing)"
        )

    def test_an_id_that_exists_nowhere_has_no_source(self) -> None:
        self.assertIsNone(self.store.describe_source("person.nobody"))

    def test_a_malformed_id_has_no_source(self) -> None:
        self.assertIsNone(self.store.describe_source("not-an-id"))

    def test_a_fetched_object_carries_its_source(self) -> None:
        self.store.store_object("place.nyc", "NYC")

        objects = self.store.get_objects(["place.nyc", "person.hero"])

        self.assertEqual(objects["place.nyc"].source, KbSource(kind="project"))
        self.assertEqual(
            objects["person.hero"].source, KbSource(kind="dataset", dataset="testing")
        )

    def test_a_linked_expansion_carries_its_source_too(self) -> None:
        """`+` walks through _fetch_one as well, so nothing arrives unstamped."""
        self.store.store_object("place.nyc", "NYC")
        self.store.add_tags("place.nyc", ["person.hero"])

        _ordered, objects = self.store.get_objects_with_links(["place.nyc+"])

        self.assertEqual(
            objects["person.hero"].source, KbSource(kind="dataset", dataset="testing")
        )


class TestDatasetPrecedence(_ProjectCase):
    """`rules.system` is a stub in both bundled datasets — later wins, and says so."""

    datasets = ["testing", "rpg"]

    def test_the_later_dataset_wins_and_names_the_loser(self) -> None:
        source = self.store.describe_source("rules.system")

        self.assertEqual(
            source, KbSource(kind="dataset", dataset="rpg", shadows=("testing",))
        )
        self.assertEqual(
            (source or KbSource("project")).label, "dataset:rpg (shadows dataset:testing)"
        )

    def test_the_reported_source_is_the_text_a_fetch_returns(self) -> None:
        """Precedence reported and precedence applied must be the same walk."""
        obj = self.store.get_objects(["rules.system"])["rules.system"]
        rpg_text = (
            Path(__file__).resolve().parents[3]
            / "datasets" / "rpg" / "knowledge" / "rules" / "system.md"
        ).read_text(encoding="utf-8")

        self.assertEqual(obj.text, rpg_text)
        self.assertEqual((obj.source or KbSource("project")).dataset, "rpg")

    def test_a_project_copy_shadows_every_dataset_holding_the_id(self) -> None:
        self.store.store_object("rules.system", "House rules.")

        source = self.store.describe_source("rules.system")

        self.assertEqual(
            source, KbSource(kind="project", shadows=("rpg", "testing"))
        )


class TestSourceIndex(_ProjectCase):
    """The bulk answer, for listings that would otherwise probe once per id."""

    datasets = ["testing"]

    def test_it_agrees_with_describe_source_for_every_visible_id(self) -> None:
        self.store.store_object("place.nyc", "NYC")
        self.store.store_object("person.hero", "My own hero.")

        index = self.store.source_index()

        self.assertEqual(set(index), set(self.store.list_ids()))
        for cid, source in index.items():
            self.assertEqual(source, self.store.describe_source(cid), cid)

    def test_it_covers_dataset_only_ids(self) -> None:
        index = self.store.source_index()

        self.assertEqual(
            index["person.villain"], KbSource(kind="dataset", dataset="testing")
        )

    def test_it_honours_the_type_filter(self) -> None:
        index = self.store.source_index(type_filter="person")

        self.assertTrue(index)
        self.assertTrue(all(cid.startswith("person.") for cid in index))

    def test_templates_are_excluded_unless_asked_for(self) -> None:
        self.assertNotIn("person._template", self.store.source_index())
        self.assertIn(
            "person._template", self.store.source_index(include_templates=True)
        )


class TestFormatting(unittest.TestCase):
    """`SOURCE=` is opt-in because KnowledgeObject.format is on the crawl path."""

    def _obj(self, source: KbSource | None) -> KnowledgeObject:
        return KnowledgeObject(
            type="person", id="person.amy", text="Amy.", tags=["pc"], source=source
        )

    def test_the_default_rendering_carries_no_source(self) -> None:
        rendered = self._obj(KbSource(kind="dataset", dataset="rpg")).format()

        self.assertEqual(rendered, "KB['person.amy']  TAGS=pc\nAmy.\n")

    def test_opting_in_puts_the_source_before_the_tags(self) -> None:
        rendered = self._obj(KbSource(kind="dataset", dataset="rpg")).format(
            include_source=True
        )

        self.assertEqual(
            rendered, "KB['person.amy']  SOURCE=dataset:rpg  TAGS=pc\nAmy.\n"
        )

    def test_an_object_with_no_known_source_says_nothing(self) -> None:
        """Silence, not a guess: an unstamped object is not evidence of 'project'."""
        rendered = self._obj(None).format(include_source=True)

        self.assertEqual(rendered, "KB['person.amy']  TAGS=pc\nAmy.\n")


class TestPayloads(unittest.TestCase):
    def test_a_missing_source_serializes_as_null(self) -> None:
        self.assertIsNone(kb_source_payload(None))

    def test_the_payload_carries_the_parts_and_the_rendered_label(self) -> None:
        payload = kb_source_payload(
            KbSource(kind="project", shadows=("rpg", "testing"))
        )

        self.assertEqual(
            payload,
            {
                "kind": "project",
                "dataset": None,
                "shadows": ["rpg", "testing"],
                "label": "project (shadows dataset:rpg, dataset:testing)",
            },
        )

    def test_an_object_payload_reports_identity_source_and_body(self) -> None:
        obj = KnowledgeObject(
            type="person",
            id="person.amy",
            text="AMY\n\nA fighter.\n\n[ note ]: #\nBody.",
            tags=["pc"],
            source=KbSource(kind="dataset", dataset="rpg"),
        )

        payload = kb_object_payload(obj, include_comments=False)

        self.assertEqual(payload["id"], "person.amy")
        self.assertEqual(payload["type"], "person")
        self.assertEqual(payload["tags"], ["pc"])
        self.assertEqual(payload["headline"], "AMY\nA fighter.")
        self.assertEqual(payload["source"], kb_source_payload(obj.source))
        self.assertNotIn("[ note ]", str(payload["content"]))


class TestCliOutput(_ProjectCase):
    """What a person — or an agent shelling out — actually reads."""

    datasets = ["testing"]

    def _run_get(self, ids: list[str], *, as_json: bool = False) -> str:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            with patch(
                "lens.core.commands.kb.find_project_root", return_value=self.root
            ):
                from lens.cli.commands.kb import get

                old = sys.stdout
                try:
                    buf = StringIO()
                    sys.stdout = buf
                    get(ids, False, facet_expand=False, as_json=as_json)
                    return buf.getvalue()
                finally:
                    sys.stdout = old

    def test_get_labels_a_dataset_object(self) -> None:
        out = self._run_get(["person.hero"])

        self.assertIn("SOURCE=dataset:testing", out)

    def test_get_labels_a_project_object(self) -> None:
        self.store.store_object("place.nyc", "NYC")

        out = self._run_get(["place.nyc"])

        self.assertIn("SOURCE=project", out)

    def test_json_carries_the_structured_source(self) -> None:
        payload = json.loads(self._run_get(["person.hero"], as_json=True))

        self.assertEqual(payload["ids"], ["person.hero"])
        item = payload["items"][0]
        self.assertEqual(item["id"], "person.hero")
        self.assertEqual(item["source"]["kind"], "dataset")
        self.assertEqual(item["source"]["dataset"], "testing")
        self.assertIn("content", item)

    def test_json_omits_ids_that_resolve_to_nothing(self) -> None:
        payload = json.loads(self._run_get(["person.nobody"], as_json=True))

        self.assertEqual(payload["ids"], [])
        self.assertEqual(payload["items"], [])


class TestWithTagJson(_ProjectCase):
    datasets = ["testing"]

    def _run_with_tag(self, tags: list[str], *, expand: bool = False) -> dict[str, Any]:
        with patch("lens.core.commands.kb.get_store", return_value=self.store):
            with patch(
                "lens.core.commands.kb.find_project_root", return_value=self.root
            ):
                from lens.cli.commands.kb import with_tag

                old = sys.stdout
                try:
                    buf = StringIO()
                    sys.stdout = buf
                    with_tag(
                        tags,
                        expand=expand,
                        recurse=None,
                        same_type_only=False,
                        type_filter=None,
                        as_json=True,
                    )
                    return json.loads(buf.getvalue())
                finally:
                    sys.stdout = old

    def test_listing_items_carry_source_and_headline_without_a_body(self) -> None:
        payload = self._run_with_tag(["protagonist"])

        self.assertEqual(payload["ids"], ["person.hero"])
        item: dict[str, Any] = payload["items"][0]
        self.assertEqual(item["source"]["label"], "dataset:testing")
        self.assertNotIn("content", item)

    def test_expanded_items_carry_the_body(self) -> None:
        payload = self._run_with_tag(["protagonist"], expand=True)

        item: dict[str, Any] = payload["items"][0]
        self.assertIn("content", item)
        self.assertEqual(item["source"]["label"], "dataset:testing")


if __name__ == "__main__":
    unittest.main()
