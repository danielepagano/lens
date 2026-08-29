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
    SKILL_RELPATH,
    CommandEntry,
    check_skill,
    collect_layers,
    describe_project,
    install_skill,
    pointer_text,
    project_skill_file,
    render_commands,
    render_guidance,
)
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

    def test_it_counts_the_merged_store_not_the_checkout(self) -> None:
        facts = describe_project(self.root)

        self.assertGreater(facts.object_count, 0)
        self.assertEqual(facts.project_owned, 0)

    def test_a_project_copy_of_a_dataset_object_reports_as_a_fork(self) -> None:
        store = KnowledgeStore.for_project(self.root)
        store.ensure_local_copy("person.hero")
        KnowledgeStore.clear_registry()

        facts = describe_project(self.root)

        self.assertIn("person.hero", facts.forks)
        self.assertEqual(facts.overrides, [])

    def test_type_names_are_not_repeated_as_tag_vocabulary(self) -> None:
        """A type matches as a tag, and the type listing already said so."""
        store = KnowledgeStore.for_project(self.root)
        store.store_object("person.rowan", "ROWAN\nA ranger.\n")
        store.add_tags("person.rowan", ["wounded"])
        KnowledgeStore.clear_registry()

        facts = describe_project(self.root)

        self.assertIn("wounded", facts.plain_tags)
        self.assertNotIn("person", facts.plain_tags)
        self.assertNotIn("pc", facts.plain_tags)

    def test_key_value_tags_are_reported_as_families_not_listed_out(self) -> None:
        store = KnowledgeStore.for_project(self.root)
        store.store_object("person.rowan", "ROWAN\nA ranger.\n")
        store.add_tags("person.rowan", ["cr:1-4", "cr:2"])
        KnowledgeStore.clear_registry()

        facts = describe_project(self.root)

        self.assertIn(("cr", 2), facts.tag_families)
        self.assertNotIn("cr:1-4", facts.plain_tags)

    def test_dot_tags_are_counted_not_listed(self) -> None:
        before = describe_project(self.root).link_tag_count
        store = KnowledgeStore.for_project(self.root)
        store.store_object("person.rowan", "ROWAN\nA ranger.\n")
        store.add_tags("person.rowan", ["location.thornwood"])
        KnowledgeStore.clear_registry()

        facts = describe_project(self.root)

        self.assertEqual(facts.link_tag_count, before + 1)
        self.assertNotIn("location.thornwood", facts.plain_tags)

    def test_registered_modules_are_reported_with_who_may_ask(self) -> None:
        facts = describe_project(self.root)

        by_id = {m.id: m for m in facts.requestable_modules}
        self.assertIn("rules.skirmish", by_id)
        self.assertEqual(by_id["rules.skirmish"].operators, ("play",))
        self.assertEqual(by_id["rules.skirmish"].dataset, "testing")

    def test_the_rendered_guidance_carries_the_live_shape(self) -> None:
        text = render_guidance(self.root)

        self.assertIn("## This project", text)
        self.assertIn("testing", text)
        self.assertIn("rules.skirmish", text)


class TestRpgDatasetLayer(_ProjectCase):
    datasets = ["rpg"]

    def test_the_rpg_dataset_explains_its_own_conventions(self) -> None:
        text = render_guidance(self.root)

        self.assertIn("Conventions of the `rpg` dataset", text)
        self.assertIn("rules.<type>", text)

    def test_design_modules_are_listed_with_a_blurb_not_their_title_line(self) -> None:
        facts = describe_project(self.root)

        blurbs = dict(facts.design_modules)
        self.assertIn("design.front", blurbs)
        self.assertTrue(blurbs["design.front"])
        self.assertFalse(blurbs["design.front"].startswith("#"))


class TestDatasetCheckout(unittest.TestCase):
    """A dataset repo is a checkout an agent works in too, and a different one.

    `get_selected_datasets` is empty there, so everything keyed off "what did
    this project opt into" reports nothing — including the module registrations
    that make the first three lines of these very files load-bearing.
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

    def test_it_reports_the_modules_the_dataset_registers_itself(self) -> None:
        facts = describe_project(self.dataset_root)

        self.assertIn("rules.skirmish", [m.id for m in facts.requestable_modules])

    def test_the_layer_being_edited_is_labelled_as_the_datasets_own(self) -> None:
        sources = [layer.source for layer in collect_layers(self.dataset_root)]

        self.assertEqual(sources, ["builtin", "generated", "dataset:self"])


class TestCommandListing(_ProjectCase):
    """Core renders the command surface; the CLI is what knows it.

    The inversion matters: core must not import Typer to say what `lens kb` is,
    so it takes plain entries and, given none, says nothing at all rather than
    falling back on a list somebody typed once.
    """

    datasets = ["testing"]

    _ENTRIES = (
        CommandEntry(name="stats", summary="Count things.", panel="Project"),
        CommandEntry(
            name="kb",
            summary="The knowledge store.",
            panel="Knowledge",
            subcommands=("add", "search", "refs"),
        ),
    )

    def test_it_groups_by_the_panel_the_cli_reports(self) -> None:
        text = render_commands(self._ENTRIES)

        self.assertIn("**Project**", text)
        self.assertIn("**Knowledge**", text)
        self.assertLess(text.index("**Project**"), text.index("**Knowledge**"))

    def test_subcommands_are_named_without_summaries(self) -> None:
        """Enough to know they exist; `--help` owns the rest and cannot drift."""
        text = render_commands(self._ENTRIES)

        self.assertIn("`add`, `search`, `refs`", text)

    def test_the_listing_is_omitted_when_no_caller_supplied_one(self) -> None:
        text = render_guidance(self.root)

        self.assertNotIn("### Commands available here", text)

    def test_the_listing_lands_in_the_generated_section(self) -> None:
        text = render_guidance(self.root, self._ENTRIES)

        self.assertIn("### Commands available here", text)
        self.assertLess(
            text.index("## This project"), text.index("### Commands available here")
        )
        self.assertLess(
            text.index("### Commands available here"), text.index("### Knowledge store")
        )
