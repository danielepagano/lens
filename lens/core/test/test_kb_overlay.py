"""Pending proposals as one precedence layer above project-local.

The gate these tests exist for: an object a session proposed must be visible to
**everything that enumerates**, not just to a fetch by name.  An id that exists
when you ask for it and does not exist when you list, expand or discover by tag
is the fail-silently class this repo keeps warning about — invisible to ``+``
expansion and to type-as-tag discovery, and indistinguishable from a real bug.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.kb_pending import KbOp, KbOpSink, inflight_ops, render_kb_ops
from lens.core.knowledge import KbSource, KnowledgeStore


def _git(tmp: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp, capture_output=True, check=True)


def _make_project(tmp: Path, datasets: list[str] | None = None) -> None:
    _git(tmp, "init")
    _git(tmp, "config", "user.email", "test@test.com")
    _git(tmp, "config", "user.name", "Test")
    body = '[project]\nnarrative = "story"\n'
    if datasets:
        listed = ", ".join(f'"{name}"' for name in datasets)
        body += f"datasets = [{listed}]\n"
    (tmp / "lens.toml").write_text(body)
    (tmp / "knowledge").mkdir()
    (tmp / "knowledge" / "tags.toml").write_text("")
    node_dir = tmp / "narrative" / "story"
    node_dir.mkdir(parents=True)
    (node_dir / "_node.md").write_text("[\n  kb_pin: []\n]: #\n\nPROLOGUE\n")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-m", "init")


class _OverlayCase(unittest.TestCase):
    datasets: list[str] = []

    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        _make_project(self.root, self.datasets)
        self.cursor = self.root / "narrative" / "story" / "_node.md"
        self.store = KnowledgeStore.for_project(self.root)

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def propose(self, *ops: KbOp) -> None:
        """Append proposals to the cursor node, the way an operator would."""
        block = render_kb_ops(ops)
        text = self.cursor.read_text()
        self.cursor.write_text(
            f"{text}\n[design\n  prompt: build it\n]: #\n\nProse.\n\n{block}\n[/design]: #\n"
        )
        self.store.evict_pending()


class TestOverlayIsVisibleEverywhere(_OverlayCase):
    """The gate. Every enumeration route, not just ``get_objects``."""

    def setUp(self) -> None:
        super().setUp()
        self.propose(
            KbOp(op="add", id="loc.vault", body="# The Vault\n\nSealed.\n"),
            KbOp(op="tag", id="loc.vault", tags=("sunken", "front.goblins")),
        )

    def test_get_objects(self) -> None:
        obj = self.store.get_objects(["loc.vault"])["loc.vault"]
        self.assertIn("Sealed.", obj.text)

    def test_exists(self) -> None:
        self.assertTrue(self.store.exists("loc.vault"))

    def test_list_ids(self) -> None:
        self.assertIn("loc.vault", self.store.list_ids())

    def test_list_ids_respects_the_type_filter(self) -> None:
        self.assertIn("loc.vault", self.store.list_ids(type_filter="loc"))
        self.assertNotIn("loc.vault", self.store.list_ids(type_filter="npc"))

    def test_list_types(self) -> None:
        self.assertIn("loc", self.store.list_types())

    def test_resolved_index(self) -> None:
        entry = self.store.resolved_index()["loc.vault"]
        self.assertEqual(entry.source.kind, "pending")
        self.assertIn("Sealed.", entry.read_text())

    def test_source_index(self) -> None:
        self.assertEqual(self.store.source_index()["loc.vault"].kind, "pending")

    def test_describe_source_reports_a_new_proposal(self) -> None:
        source = self.store.describe_source("loc.vault")
        self.assertEqual(source, KbSource(kind="pending"))
        self.assertEqual((source or KbSource("project")).label, "pending (new)")

    def test_get_tags(self) -> None:
        self.assertEqual(self.store.get_tags("loc.vault"), ["front.goblins", "sunken"])

    def test_get_ids_with_tag(self) -> None:
        self.assertIn("loc.vault", self.store.get_ids_with_tag("sunken"))

    def test_type_as_tag_discovery(self) -> None:
        # A bare token naming a type matches every object of that type — the
        # route `design` uses to find modules without a hand-maintained tag.
        self.assertIn("loc.vault", self.store.get_ids_with_tag("loc"))

    def test_list_unique_tags(self) -> None:
        self.assertIn("sunken", self.store.list_unique_tags())

    def test_plus_expansion_reaches_a_proposed_object(self) -> None:
        self.store.store_object("npc.vasa", "Vasa")
        self.store.add_tags("npc.vasa", ["loc.vault"])
        ordered, objects = self.store.get_objects_with_links(["npc.vasa+"])
        self.assertIn("loc.vault", ordered)
        self.assertIn("Sealed.", objects["loc.vault"].text)

    def test_facet_listing(self) -> None:
        self.propose(KbOp(op="add", id="loc.vault-cistern", body="Cistern"))
        self.assertIn("loc.vault-cistern", self.store.list_facet_ids("loc.vault"))

    def test_the_crawl_renders_no_source_for_a_proposal(self) -> None:
        # During generation a proposed object is world truth; which tree it came
        # from is not part of that, and `format` defaults `include_source` off.
        obj = self.store.get_objects(["loc.vault"])["loc.vault"]
        self.assertNotIn("SOURCE=", obj.format())
        self.assertIn("SOURCE=", obj.format(include_source=True))


class TestOverlayOverAnExistingObject(_OverlayCase):
    def test_patch_serves_the_folded_text_and_names_its_base(self) -> None:
        self.store.store_object("loc.vault", "alpha\nbeta\n")
        self.propose(
            KbOp(
                op="patch",
                id="loc.vault",
                patches=({"start": {"target": "beta"}, "content": "BETA"},),
            )
        )
        obj = self.store.get_objects(["loc.vault"])["loc.vault"]
        self.assertIn("BETA", obj.text)
        self.assertEqual((obj.source or KbSource("project")).kind, "pending")
        self.assertEqual((obj.source or KbSource("project")).label, "pending (over project)")

    def test_nothing_is_written_to_disk(self) -> None:
        self.store.store_object("loc.vault", "alpha\n")
        self.propose(KbOp(op="add", id="loc.vault", body="rewritten\n"))
        self.assertIn("rewritten", self.store.get_objects(["loc.vault"])["loc.vault"].text)
        on_disk = (self.root / "knowledge" / "loc" / "vault.md").read_text()
        self.assertEqual(on_disk, "alpha\n")

    def test_removing_a_project_object_hides_it_everywhere(self) -> None:
        self.store.store_object("loc.vault", "alpha\n")
        self.store.add_tags("loc.vault", ["sunken"])
        self.propose(KbOp(op="remove", id="loc.vault"))
        self.assertFalse(self.store.exists("loc.vault"))
        self.assertIsNone(self.store.get_objects(["loc.vault"]).get("loc.vault"))
        self.assertNotIn("loc.vault", self.store.list_ids())
        self.assertNotIn("loc.vault", self.store.resolved_index())
        self.assertNotIn("loc.vault", self.store.get_ids_with_tag("sunken"))
        self.assertTrue((self.root / "knowledge" / "loc" / "vault.md").exists())


class TestOverlayWithDatasets(_OverlayCase):
    datasets = ["testing"]

    def test_removing_a_project_fork_falls_back_to_the_dataset(self) -> None:
        # `removed` means the project file goes away, not that the id is gone.
        # An overlay that predicted otherwise would disagree with the world it
        # is standing in front of.
        self.store.store_object("person.hero", "A project fork.\n")
        self.assertEqual(self.store.describe_source("person.hero"), KbSource(kind="project", shadows=("testing",)))

        self.propose(KbOp(op="remove", id="person.hero"))

        self.assertTrue(self.store.exists("person.hero"))
        obj = self.store.get_objects(["person.hero"])["person.hero"]
        self.assertNotIn("A project fork.", obj.text)
        source = obj.source or KbSource("project")
        self.assertEqual(source.kind, "pending")
        self.assertEqual(source.label, "pending (over dataset:testing)")
        self.assertIn("person.hero", self.store.list_ids())

    def test_a_dataset_store_never_sees_the_overlay(self) -> None:
        self.propose(KbOp(op="add", id="person.ghost", body="not a dataset object"))
        for ds in self.store._dataset_stores:  # pyright: ignore[reportPrivateUsage]
            self.assertFalse(ds.exists("person.ghost"))
            self.assertNotIn("person.ghost", ds.list_ids())


class TestOverlayDerivation(_OverlayCase):
    def test_no_proposals_means_no_layer(self) -> None:
        self.assertTrue(self.store.pending_layer().is_empty())

    def test_the_layer_follows_the_cursor(self) -> None:
        # Navigating away turns the overlay off and writes nothing either way.
        self.propose(KbOp(op="add", id="loc.vault", body="Sealed"))
        self.assertTrue(self.store.exists("loc.vault"))

        (self.root / "lens.toml").write_text('[project]\nnarrative = "other"\n')
        other = self.root / "narrative" / "other"
        other.mkdir(parents=True)
        (other / "_node.md").write_text("Elsewhere.\n")
        KnowledgeStore.clear_registry()
        moved = KnowledgeStore.for_project(self.root)

        self.assertFalse(moved.exists("loc.vault"))
        self.assertFalse((self.root / "knowledge" / "loc" / "vault.md").exists())

    def test_editing_the_node_re_folds(self) -> None:
        self.propose(KbOp(op="add", id="loc.vault", body="first"))
        self.assertIn("first", self.store.get_objects(["loc.vault"])["loc.vault"].text)

        # A retry truncates the block out; the overlay must follow.
        self.cursor.write_text("[\n  kb_pin: []\n]: #\n\nPROLOGUE\n")
        self.store.evict_pending()
        self.assertFalse(self.store.exists("loc.vault"))

    def test_tags_toml_is_never_touched_by_the_overlay(self) -> None:
        before = (self.root / "knowledge" / "tags.toml").read_text()
        self.propose(KbOp(op="add", id="loc.vault", body="b"),
                     KbOp(op="tag", id="loc.vault", tags=("sunken",)))
        self.assertIn("loc.vault", self.store.get_ids_with_tag("sunken"))
        self.assertEqual((self.root / "knowledge" / "tags.toml").read_text(), before)

    def test_a_writer_still_sees_the_disk_truth(self) -> None:
        # store_object decides copy-on-write from `exists and not _is_local`.
        # If the overlay reached that, a session-created id would take the
        # dataset copy-on-write branch instead of being written.
        self.propose(KbOp(op="add", id="loc.vault", body="proposed"))
        self.store.store_object("loc.vault", "written by hand")
        self.assertEqual(
            (self.root / "knowledge" / "loc" / "vault.md").read_text(),
            "written by hand",
        )

    def test_materialization_view_ignores_proposals(self) -> None:
        self.propose(KbOp(op="add", id="loc.vault", body="proposed"))
        plain = KnowledgeStore.for_project(self.root, pending=False)
        self.assertFalse(plain.exists("loc.vault"))
        self.assertNotIn("loc.vault", plain.list_ids())
        self.assertTrue(self.store.exists("loc.vault"))


class TestInflightOverlay(_OverlayCase):
    def test_an_op_is_visible_before_anything_is_persisted(self) -> None:
        # A kb_get after a kb_add in the same turn must see the new object.
        sink = KbOpSink()
        sink.record(KbOp(op="add", id="loc.vault", body="mid-generation"))
        with inflight_ops(self.root, sink):
            self.assertTrue(self.store.exists("loc.vault"))
            self.assertIn("loc.vault", self.store.list_ids())
        self.assertFalse(self.store.exists("loc.vault"))

    def test_in_flight_ops_compose_on_top_of_persisted_ones(self) -> None:
        self.propose(KbOp(op="add", id="loc.vault", body="turn one"))
        sink = KbOpSink()
        sink.record(
            KbOp(
                op="patch",
                id="loc.vault",
                patches=({"start": {"target": "turn one"}, "content": "turn two"},),
            )
        )
        with inflight_ops(self.root, sink):
            self.assertIn(
                "turn two", self.store.get_objects(["loc.vault"])["loc.vault"].text
            )

    def test_recording_mid_context_is_seen_without_an_explicit_evict(self) -> None:
        sink = KbOpSink()
        with inflight_ops(self.root, sink):
            self.assertFalse(self.store.exists("loc.vault"))
            sink.record(KbOp(op="add", id="loc.vault", body="added later"))
            self.assertTrue(self.store.exists("loc.vault"))


class TestDiscoverySurfaces(_OverlayCase):
    """`kb search` and `kb list` read the same index and must not crash on a
    proposal, which has no file to open."""

    def test_search_matches_a_proposed_body(self) -> None:
        from lens.core.commands.kb_search import kb_search

        self.propose(KbOp(op="add", id="loc.vault", body="a flooded cistern\n"))
        result = kb_search("flooded", store=self.store)
        self.assertEqual([hit.id for hit in result.hits], ["loc.vault"])
        self.assertEqual(result.hits[0].source.kind, "pending")

    def test_search_can_filter_to_proposals(self) -> None:
        from lens.core.commands.kb_search import kb_search

        self.store.store_object("loc.old", "a flooded ruin\n")
        self.propose(KbOp(op="add", id="loc.vault", body="a flooded cistern\n"))
        result = kb_search("flooded", source="pending", store=self.store)
        self.assertEqual([hit.id for hit in result.hits], ["loc.vault"])

    def test_list_prints_a_headline_for_a_proposal(self) -> None:
        from lens.core.commands.kb_search import kb_list

        self.propose(KbOp(op="add", id="loc.vault", body="# The Vault\n\nSealed.\n"))
        entries = {entry.id: entry for entry in kb_list(store=self.store)}
        self.assertIn("The Vault", entries["loc.vault"].headline)

    def test_skill_facts_ignore_the_cursor(self) -> None:
        from lens.core.commands.skill import describe_project

        before = describe_project(self.root).object_count
        self.propose(KbOp(op="add", id="loc.vault", body="Sealed"))
        self.assertEqual(describe_project(self.root).object_count, before)


class TestOverlayErrorsAreVisible(_OverlayCase):
    def test_a_stale_patch_reports_instead_of_dropping_silently(self) -> None:
        self.store.store_object("loc.vault", "the anchor line\n")
        self.propose(
            KbOp(
                op="patch",
                id="loc.vault",
                patches=({"start": {"target": "the anchor line"}, "content": "new"},),
            )
        )
        self.assertIn("new", self.store.get_objects(["loc.vault"])["loc.vault"].text)

        # The user hand-edits the object, taking the anchor with it.
        (self.root / "knowledge" / "loc" / "vault.md").write_text("rewritten by hand\n")
        self.store.evict_pending()

        layer = self.store.pending_layer()
        self.assertEqual(len(layer.errors), 1)
        self.assertIn("loc.vault", str(layer.errors[0]))
        self.assertIn(
            "rewritten by hand",
            self.store.get_objects(["loc.vault"])["loc.vault"].text,
        )


if __name__ == "__main__":
    unittest.main()
