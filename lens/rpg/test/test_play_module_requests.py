"""`play` picks up module declarations from an active dataset (issue #136).

Uses the bundled ``testing`` dataset, which registers ``rules.skirmish`` for
``play``, so this covers real dataset resolution rather than a temp manifest.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import CrawlSpec, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.module_requests import clear_module_registry, unloaded_modules
from lens.core.narrative import NarrativeNode

MODULE_ID = "rules.skirmish"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


class TestPlayModuleRequests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init")
        _git(self.root, "config", "user.email", "test@test.com")
        _git(self.root, "config", "user.name", "Test")
        (self.root / "lens.toml").write_text(
            '[project]\nnarrative = "test"\ndatasets = ["rpg", "testing"]\n'
            '[[llm]]\nbase_url = "https://api.example.com/v1"\nmodel = "test"\n',
            encoding="utf-8",
        )
        self.narrative_dir = self.root / "narrative" / "test"
        self.narrative_dir.mkdir(parents=True)
        (self.narrative_dir / "_node.md").write_text("# test\n", encoding="utf-8")
        (self.root / "knowledge").mkdir(exist_ok=True)
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

    def _node(self, body: str = "# test\n") -> NarrativeNode:
        (self.narrative_dir / "_node.md").write_text(body, encoding="utf-8")
        return NarrativeNode(narrative_root=self.narrative_dir, key_path=())

    def test_dataset_module_is_offered_to_play(self) -> None:
        result = crawl(CrawlSpec.of(self._node()))

        self.assertEqual(
            [d.kb_id for d in unloaded_modules(self.root, "play", result)], [MODULE_ID]
        )

    def test_not_offered_to_other_operators(self) -> None:
        result = crawl(CrawlSpec.of(self._node()))

        self.assertEqual(unloaded_modules(self.root, "write", result), ())

    def test_include_in_the_session_node_takes_it_out_of_the_catalog(self) -> None:
        node = self._node(f"# test\n\n[include: {MODULE_ID}]: #\n")

        result = crawl(CrawlSpec.of(node))

        self.assertIn("KB['rules.skirmish']", result.current_content or "")
        self.assertEqual(unloaded_modules(self.root, "play", result), ())


if __name__ == "__main__":
    unittest.main()
