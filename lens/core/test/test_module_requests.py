"""Unit tests for model-requested modules: registry, catalog filter, tool."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lens.core.context import CrawlResult, CrawlSpec, assemble_prompt, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.module_requests import (
    LOAD_MODULE_TOOL,
    ModuleDecl,
    ModuleRequestSink,
    build_module_request_bundle,
    clear_module_registry,
    dataset_modules,
    module_task_hint,
    modules_for_operator,
    unloaded_modules,
)
from lens.core.narrative import NarrativeNode

MODULE_BODY = (
    "# Skirmish\n"
    "\n"
    "Turn order and damage. Load when violence starts.\n"
    "\n"
    "Roll off, higher wins.\n"
)
"""First three lines are the catalog entry; the body is what `load_module` returns."""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


def _init_repo(tmp: Path) -> None:
    _git(tmp, "init")
    _git(tmp, "config", "user.email", "test@test.com")
    _git(tmp, "config", "user.name", "Test")


def _write_dataset(path: Path, toml_body: str) -> None:
    """A dataset directory with one rules module and a lens.toml manifest."""
    (path / "knowledge" / "rules").mkdir(parents=True, exist_ok=True)
    (path / "knowledge" / "rules" / "skirmish.md").write_text(
        MODULE_BODY, encoding="utf-8"
    )
    (path / "lens.toml").write_text(toml_body, encoding="utf-8")


VALID_MANIFEST = """\
[dataset]

[[dataset.modules]]
id = "rules.skirmish"
operators = ["play", "write"]
"""


class _ProjectFixture(unittest.TestCase):
    """Project whose only dataset is a temp directory declaring modules."""

    manifest: str = VALID_MANIFEST

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "project"
        self.root.mkdir()
        _init_repo(self.root)
        self.dataset = base / "moduleset"
        self.dataset.mkdir()
        _write_dataset(self.dataset, self.manifest)

        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "story"\ndatasets = ["moduleset"]\n'
            '[[llm]]\nbase_url = "http://127.0.0.1:1"\nmodel = "x"\n',
            encoding="utf-8",
        )
        (self.root / "lens.local.toml").write_text(
            f'[dataset_paths]\nmoduleset = "{self.dataset}"\n', encoding="utf-8"
        )
        (self.root / "knowledge").mkdir()
        self.narrative_dir = self.root / "narrative" / "story"
        self.narrative_dir.mkdir(parents=True)
        (self.narrative_dir / "_node.md").write_text("Kira waits.\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-m", "project")
        clear_module_registry()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def tearDown(self) -> None:
        clear_module_registry()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self._tmp.cleanup()

    def node(self) -> NarrativeNode:
        return NarrativeNode(narrative_root=self.narrative_dir, key_path=())

    def write_node(self, text: str) -> NarrativeNode:
        (self.narrative_dir / "_node.md").write_text(text, encoding="utf-8")
        return self.node()


class TestRegistry(_ProjectFixture):
    def test_declaration_is_read_from_the_dataset_manifest(self) -> None:
        decls = dataset_modules(self.root)

        self.assertEqual([d.kb_id for d in decls], ["rules.skirmish"])
        self.assertEqual(decls[0].operators, ("play", "write"))
        self.assertEqual(decls[0].dataset, "moduleset")

    def test_filtered_by_target_operator(self) -> None:
        self.assertEqual(
            [d.kb_id for d in modules_for_operator(self.root, "play")],
            ["rules.skirmish"],
        )
        self.assertEqual(modules_for_operator(self.root, "chat"), ())

    def test_inactive_dataset_contributes_nothing(self) -> None:
        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "story"\ndatasets = []\n', encoding="utf-8"
        )
        clear_module_registry()

        self.assertEqual(dataset_modules(self.root), ())


class TestMalformedDeclarations(_ProjectFixture):
    manifest = """\
[dataset]

[[dataset.modules]]
operators = ["play"]

[[dataset.modules]]
id = "rules.other"

[[dataset.modules]]
id = "rules.skirmish"
operators = ["play"]
"""

    def test_incomplete_entries_are_skipped_not_fatal(self) -> None:
        """A dataset is third-party content: one bad table must not break the project."""
        decls = dataset_modules(self.root)

        self.assertEqual([d.kb_id for d in decls], ["rules.skirmish"])


class TestDescriptionFromHeadline(_ProjectFixture):
    def _offer(self) -> tuple[ModuleDecl, ...]:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        return unloaded_modules(self.root, "play", crawl(CrawlSpec.of(self.node())))

    def test_catalog_entry_is_the_objects_first_three_lines(self) -> None:
        decls = self._offer()

        self.assertEqual(
            [d.description for d in decls],
            ["# Skirmish\nTurn order and damage. Load when violence starts."],
        )

    def test_a_body_that_describes_itself_in_no_lines_is_not_offered(self) -> None:
        """Nothing to choose on is worse than no choice at all."""
        (self.dataset / "knowledge" / "rules" / "skirmish.md").write_text(
            "\n\n\nRoll off, higher wins.\n", encoding="utf-8"
        )

        self.assertEqual(self._offer(), ())

    def test_headline_tracks_the_file_without_touching_the_manifest(self) -> None:
        (self.dataset / "knowledge" / "rules" / "skirmish.md").write_text(
            "# Skirmish\n\nNow about duels only.\n\nRoll off.\n", encoding="utf-8"
        )

        self.assertEqual(
            [d.description for d in self._offer()],
            ["# Skirmish\nNow about duels only."],
        )


class TestCatalogFilter(_ProjectFixture):
    def _crawl(self, node: NarrativeNode, **kwargs: Any) -> CrawlResult:
        return crawl(CrawlSpec.of(node, **kwargs))

    def test_offered_when_out_of_scope(self) -> None:
        decls = unloaded_modules(self.root, "play", self._crawl(self.node()))

        self.assertEqual([d.kb_id for d in decls], ["rules.skirmish"])

    def test_a_pin_takes_it_off_the_menu(self) -> None:
        result = self._crawl(self.node(), extra_pins=["rules.skirmish"])

        self.assertEqual(unloaded_modules(self.root, "play", result), ())

    def test_an_include_takes_it_off_the_menu(self) -> None:
        """The latch: once written into the node it must never be offered again."""
        node = self.write_node("Kira waits.\n\n[include: rules.skirmish]: #\n")

        result = self._crawl(node)

        self.assertIn("KB['rules.skirmish']", result.current_content or "")
        self.assertEqual(unloaded_modules(self.root, "play", result), ())

    def test_a_mention_takes_it_off_the_menu(self) -> None:
        node = self.write_node("Kira waits.\n\n[mention: rules.skirmish]: #\n")

        self.assertEqual(unloaded_modules(self.root, "play", self._crawl(node)), ())

    def test_a_session_module_takes_it_off_the_menu(self) -> None:
        """`play --module skirmish` pre-declares it; the tool must not re-offer it."""
        result = self._crawl(self.node(), modules=["rules.skirmish"])

        self.assertEqual(unloaded_modules(self.root, "play", result), ())

    def test_registered_id_with_no_kb_object_is_not_offered(self) -> None:
        (self.dataset / "knowledge" / "rules" / "skirmish.md").unlink()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

        self.assertEqual(
            unloaded_modules(self.root, "play", self._crawl(self.node())), ()
        )

    def test_other_operators_get_nothing(self) -> None:
        self.assertEqual(
            unloaded_modules(self.root, "chat", self._crawl(self.node())), ()
        )

    def test_an_inline_expansion_takes_it_off_the_menu(self) -> None:
        """An `inline`-tagged `@type.key` splices the object into the prose itself.

        The model is looking at the full text, so offering to fetch it again buys
        a round trip and an include that duplicates nothing.
        """
        KnowledgeStore.for_project(self.root).add_tags("rules.skirmish", ["inline"])
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        node = self.write_node("Kira waits, checking @rules.skirmish.\n")

        result = self._crawl(node)
        # Sanity: the object really was spliced in, not just referenced.
        assemble_prompt(result, system_prompt="s", instruction="i")

        self.assertEqual(unloaded_modules(self.root, "play", result), ())


class TestToolBundle(_ProjectFixture):
    def _bundle(self) -> tuple[Any, ModuleRequestSink]:
        sink = ModuleRequestSink()
        decls = unloaded_modules(self.root, "play", crawl(CrawlSpec.of(self.node())))
        bundle = build_module_request_bundle(decls, sink, self.root)
        assert bundle is not None
        return bundle, sink

    def _call(self, bundle: Any, args: dict[str, Any]) -> str:
        handler = bundle.handlers[LOAD_MODULE_TOOL]
        return asyncio.run(handler(args, self.root))

    def test_no_modules_means_no_tool_at_all(self) -> None:
        self.assertIsNone(build_module_request_bundle((), ModuleRequestSink(), self.root))

    def test_schema_is_single_id_and_enumerated(self) -> None:
        bundle, _ = self._bundle()
        fn = bundle.tools[0]["function"]
        params = fn["parameters"]

        self.assertEqual(fn["name"], LOAD_MODULE_TOOL)
        self.assertEqual(params["required"], ["module"])
        self.assertEqual(params["properties"]["module"]["enum"], ["rules.skirmish"])
        self.assertIn("rules.skirmish", fn["description"])
        self.assertIn("violence starts", fn["description"])

    def test_call_returns_content_and_records_the_id(self) -> None:
        bundle, sink = self._bundle()

        result = self._call(bundle, {"module": "rules.skirmish"})

        self.assertIn("KB['rules.skirmish']", result)
        self.assertIn("Roll off, higher wins.", result)
        self.assertEqual(sink.loaded, ["rules.skirmish"])
        self.assertEqual(
            sink.include_annotations(), "[include: rules.skirmish]: #"
        )

    def test_second_call_does_not_pay_for_the_body_twice(self) -> None:
        bundle, sink = self._bundle()
        self._call(bundle, {"module": "rules.skirmish"})

        result = self._call(bundle, {"module": "rules.skirmish"})

        self.assertNotIn("Roll off, higher wins.", result)
        self.assertEqual(sink.loaded, ["rules.skirmish"])

    def test_a_module_that_delivers_nothing_does_not_latch(self) -> None:
        """No include for content the model never got.

        The object can go away between the crawl that built the catalog and the
        call.  Recording the id anyway would write scope into the node that the
        reader sees and the model never received.
        """
        bundle, sink = self._bundle()
        (self.dataset / "knowledge" / "rules" / "skirmish.md").unlink()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

        result = self._call(bundle, {"module": "rules.skirmish"})

        self.assertTrue(result.startswith("(error:"))
        self.assertEqual(sink.loaded, [])
        self.assertEqual(sink.include_annotations(), "")

    def test_unknown_id_is_rejected_with_the_valid_list(self) -> None:
        bundle, sink = self._bundle()

        result = self._call(bundle, {"module": "rules.nonsense"})

        self.assertTrue(result.startswith("(error:"))
        self.assertIn("rules.skirmish", result)
        self.assertEqual(sink.loaded, [])

    def test_missing_argument_is_rejected(self) -> None:
        bundle, _ = self._bundle()

        self.assertTrue(self._call(bundle, {}).startswith("(error:"))


class TestTaskHint(_ProjectFixture):
    def test_hint_lists_unloaded_modules(self) -> None:
        decls = unloaded_modules(self.root, "play", crawl(CrawlSpec.of(self.node())))

        hint = module_task_hint(decls, self.root)

        self.assertIn("load_module", hint)
        self.assertIn("rules.skirmish", hint)
        self.assertIn("violence starts", hint)

    def test_nothing_to_offer_means_no_hint(self) -> None:
        self.assertEqual(module_task_hint((), self.root), "")


if __name__ == "__main__":
    unittest.main()
