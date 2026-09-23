"""What `lens skill` emits, and what stays out of the file it commits.

The split is the whole design, so it is what these pin. The *pointer* written
into a project must contain nothing that can go stale — no dataset list, no
counts, no ids — because it is compared byte for byte to detect drift, and a
pointer that changed when somebody added a knowledge object would report drift
that is not there. The *emitted guidance* is the opposite: it must actually read
the project, or there was no reason to generate it instead of writing it down.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.commands.skill import (
    GIST_BREAK,
    SKILL_RELPATH,
    check_skill,
    collect_layers,
    describe_project,
    install_skill,
    pointer_text,
    project_skill_file,
    render_guidance,
    render_topic,
    topic_names,
)
from lens.core.exceptions import LensException
from lens.core.knowledge import KnowledgeStore
from lens.core.module_requests import clear_module_registry


def _make_project(tmp: Path, datasets: list[str] | None = None) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, check=True
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
        clear_module_registry()
        self.tmp = tempfile.mkdtemp(prefix="lens_skill_")
        self.root = Path(self.tmp)
        _make_project(self.root, self.datasets)

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        clear_module_registry()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestPointer(_ProjectCase):
    datasets = ["testing"]

    def test_the_pointer_names_no_project_fact(self) -> None:
        """Everything a pointer states is a thing that can go stale."""
        text = pointer_text()

        self.assertNotIn(str(self.root), text)
        self.assertNotIn("testing", text)
        for volatile in ("person.hero", "place.dungeon", "design.", "rules."):
            self.assertNotIn(volatile, text)

    def test_the_pointer_carries_frontmatter_so_a_host_finds_it_unprompted(self) -> None:
        text = pointer_text()

        self.assertTrue(text.startswith("---\n"))
        head = text.split("---", 2)[1]
        self.assertIn("name: lens", head)
        self.assertIn("description:", head)

    def test_the_pointer_states_the_invariants_that_survive_lens_being_absent(self) -> None:
        text = pointer_text().lower()

        self.assertIn("lens skill", text)
        self.assertIn("tags.toml", text)
        self.assertIn("dataset", text)

    def test_install_writes_the_pointer_and_check_agrees(self) -> None:
        path = install_skill(self.root)

        self.assertEqual(path, self.root / SKILL_RELPATH)
        self.assertEqual(path.read_text(encoding="utf-8"), pointer_text())
        self.assertTrue(check_skill(self.root).ok)

    def test_a_missing_pointer_is_not_ok_and_says_so(self) -> None:
        state = check_skill(self.root)

        self.assertFalse(state.ok)
        self.assertFalse(state.installed)
        self.assertIn("not installed", state.message())

    def test_an_edited_pointer_reads_as_drift(self) -> None:
        path = install_skill(self.root)
        path.write_text(path.read_text(encoding="utf-8") + "\nlocal note\n", encoding="utf-8")

        state = check_skill(self.root)

        self.assertTrue(state.installed)
        self.assertFalse(state.current)
        self.assertIn("stale", state.message())

    def test_adding_knowledge_does_not_drift_the_pointer(self) -> None:
        install_skill(self.root)
        store = KnowledgeStore.for_project(self.root)
        store.store_object("person.new", "NEW\nSomebody.\n")
        store.add_tags("person.new", ["pc"])

        self.assertTrue(check_skill(self.root).ok)

    def test_install_is_idempotent(self) -> None:
        first = install_skill(self.root).read_text(encoding="utf-8")
        second = install_skill(self.root).read_text(encoding="utf-8")

        self.assertEqual(first, second)


class TestLayers(_ProjectCase):
    datasets = ["testing"]

    def test_layers_compose_bundled_then_generated_then_dataset_then_project(self) -> None:
        project_skill_file(self.root).parent.mkdir(parents=True, exist_ok=True)
        project_skill_file(self.root).write_text("## House rules\n\nAsk first.\n")

        sources = [layer.source for layer in collect_layers(self.root)]

        self.assertEqual(
            sources, ["builtin", "generated", "dataset:testing", "project"]
        )

    def test_the_project_layer_comes_last_so_house_rules_win_the_argument(self) -> None:
        project_skill_file(self.root).parent.mkdir(parents=True, exist_ok=True)
        project_skill_file(self.root).write_text("## House rules\n\nAsk first.\n")

        text = render_guidance(self.root)

        self.assertTrue(text.rstrip().endswith("Ask first."))

    def test_a_dataset_without_a_skill_file_contributes_no_layer(self) -> None:
        sources = [layer.source for layer in collect_layers(self.root)]

        self.assertIn("dataset:testing", sources)
        self.assertEqual(sources.count("dataset:testing"), 1)

    def test_no_project_still_emits_the_bundled_invariants(self) -> None:
        """The case where an agent needs them most: nothing resolves yet."""
        layers = collect_layers(None)

        self.assertEqual([layer.source for layer in layers], ["builtin"])
        self.assertIn("tags.toml", render_guidance(None))


class TestGeneratedFacts(_ProjectCase):
    datasets = ["testing"]

    def test_it_reports_the_datasets_and_that_they_resolve_outside_the_repo(self) -> None:
        facts = describe_project(self.root)

        self.assertEqual(facts.datasets, ["testing"])
        detail = facts.dataset_details[0]
        self.assertIsNotNone(detail.path)
        self.assertFalse(detail.inside_repo)

    def test_the_rendered_guidance_carries_the_live_shape(self) -> None:
        text = render_guidance(self.root)

        self.assertIn("## This project", text)
        self.assertIn("`testing`", text)

    def test_it_names_the_cursor_so_an_agent_knows_where_work_lands(self) -> None:
        narrative = self.root / "narrative" / "tale"
        narrative.mkdir(parents=True)
        (narrative / "_node.md").write_text("# Tale\n")
        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "tale"\ndatasets = ["testing"]\n'
        )

        facts = describe_project(self.root)
        text = render_guidance(self.root)

        self.assertEqual(facts.active_narrative, "tale")
        self.assertIsNotNone(facts.cursor)
        self.assertIn(f"the cursor is `{facts.cursor}`", text)

    def test_no_narrative_says_how_to_get_one(self) -> None:
        self.assertIn("lens use <slug>", render_guidance(self.root))

    def test_inventories_are_left_to_the_commands_that_own_them(self) -> None:
        """Read once, often truncated: a list another command prints is dead weight."""
        text = render_guidance(self.root)

        self.assertNotIn("rules.skirmish", text)
        self.assertIn("lens stats", text)
        self.assertIn("lens --help", text)

    def test_a_dataset_file_without_a_gist_break_is_emitted_whole(self) -> None:
        """A dataset that never adopted the split loses nothing."""
        text = render_guidance(self.root)

        self.assertIn("Fixtures only.", text)
        self.assertNotIn("lens skill testing", text)


class TestDatasetTopics(_ProjectCase):
    """A dataset's gist is always emitted; its full conventions are one call away."""

    datasets = ["rpg", "companion"]

    def test_the_gist_is_emitted_and_names_the_topic(self) -> None:
        text = render_guidance(self.root)

        self.assertIn("Conventions of the `rpg` dataset", text)
        self.assertIn("Full conventions: `lens skill rpg`", text)
        self.assertIn("Full conventions: `lens skill companion`", text)
        self.assertNotIn("Deltas only", text)
        self.assertNotIn(GIST_BREAK, text)

    def test_the_topic_is_the_whole_file_gist_included(self) -> None:
        text = render_topic(self.root, "rpg")

        self.assertIn("Conventions of the `rpg` dataset", text)
        self.assertIn("Deltas only", text)
        self.assertIn("rules.<type>", text)
        self.assertNotIn(GIST_BREAK, text)
        self.assertNotIn("Full conventions:", text)

    def test_topics_are_the_active_datasets_that_ship_a_skill_file(self) -> None:
        self.assertEqual(topic_names(self.root), ["rpg", "companion"])

    def test_an_unknown_topic_names_the_ones_that_exist(self) -> None:
        with self.assertRaises(LensException) as caught:
            render_topic(self.root, "dnd")

        self.assertIn("rpg, companion", str(caught.exception))

    def test_the_main_output_fits_one_read(self) -> None:
        """Truncation is the failure this guards: an agent reads the output once,
        through a tool that cuts long results. Grow a topic, not this."""
        self.assertLess(len(render_guidance(self.root)), 12_000)


class TestDatasetCheckout(unittest.TestCase):
    """A dataset repo is a checkout an agent works in too, and a different one.

    `get_selected_datasets` is empty there, so everything keyed off "what did
    this project opt into" reports nothing, and the dataset's own skill file is
    the project layer, emitted whole.
    """

    def setUp(self) -> None:
        KnowledgeStore.clear_registry()
        clear_module_registry()
        self.dataset_root = Path(__file__).resolve().parents[3] / "datasets" / "testing"

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        clear_module_registry()

    def test_it_knows_it_is_a_dataset(self) -> None:
        facts = describe_project(self.dataset_root)

        self.assertTrue(facts.is_dataset)
        self.assertEqual(facts.datasets, [])

    def test_the_layer_being_edited_is_labelled_as_the_datasets_own(self) -> None:
        sources = [layer.source for layer in collect_layers(self.dataset_root)]

        self.assertEqual(sources, ["builtin", "generated", "dataset:self"])
