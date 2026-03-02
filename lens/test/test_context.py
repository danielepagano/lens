"""Unit tests for lens.context: crawl and assemble_prompt."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lens.core.context import (
    CrawlResult,
    assemble_prompt,
    assemble_prompt_kb_edit,
    crawl,
    crawl_result_from_pins,
    SYSTEM_PROMPT_FORMATTING_ADDENDUM,
)
from lens.core.narrative import NarrativeNode


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, capture_output=True, check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def _make_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    kb_dir = tmp / "knowledge"
    kb_dir.mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp, capture_output=True, check=True,
    )
    node = NarrativeNode(narrative_root=narrative_dir, key_path=())
    return tmp, node


def _add_kb(root: Path, type_name: str, key: str, content: str) -> None:
    path = root / "knowledge" / type_name / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", f"kb {type_name}.{key}"], cwd=root, capture_output=True, check=True)


class TestCrawlNoPins(unittest.TestCase):
    def test_empty_knowledge_when_no_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _root, node = _make_project(_init_repo(Path(tmp)))
            r = crawl(node)
            self.assertEqual(r.knowledge, [])


class TestCrawlPinOrder(unittest.TestCase):
    def test_pins_from_root_before_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "a", "Place A")
            _add_kb(root, "place", "b", "Place B")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.a\n]: #\n\n# test\n")
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  kb_pin:\n    - place.b\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            child = node.child_node("ch1")
            r = crawl(child)
            self.assertEqual(len(r.knowledge), 2)
            self.assertIn("place.a", r.knowledge[0])
            self.assertIn("place.b", r.knowledge[1])


class TestCrawlUnpin(unittest.TestCase):
    def test_unpin_at_child_cancels_ancestor_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "x", "Place X")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.x\n]: #\n\n# test\n")
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  kb_unpin:\n    - place.x\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            child = node.child_node("ch1")
            r = crawl(child)
            self.assertEqual(r.knowledge, [])

    def test_unpin_at_ancestor_does_not_cancel_descendant_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "x", "Place X")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.x\n  kb_unpin:\n    - place.x\n]: #\n\n# test\n")
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  kb_pin:\n    - place.x\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            child = node.child_node("ch1")
            r = crawl(child)
            self.assertEqual(len(r.knowledge), 1)
            self.assertIn("place.x", r.knowledge[0])


class TestCrawlDedup(unittest.TestCase):
    def test_same_id_pinned_multiple_levels_appears_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "a", "Place A")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.a\n]: #\n\n# test\n")
            (node.narrative_root / "ch1").mkdir()
            (node.narrative_root / "ch1" / "_node.md").write_text(
                "[\n  kb_pin:\n    - place.a\n]: #\n\n# ch1\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            child = node.child_node("ch1")
            r = crawl(child)
            self.assertEqual(len(r.knowledge), 1)


class TestCrawlExtraPins(unittest.TestCase):
    def test_extra_pins_override_ancestor_unpins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "x", "Place X")
            root_node = NarrativeNode(narrative_root=node.narrative_root, key_path=())
            md = root_node.md_path()
            md.write_text("[\n  kb_unpin:\n    - place.x\n]: #\n\n# test\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            r = crawl(node, extra_pins=["place.x"])
            self.assertEqual(len(r.knowledge), 1)


def _write_node(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _commit(root: Path, msg: str = "update") -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=root, capture_output=True, check=True)


class TestCrawlNarrative(unittest.TestCase):
    def test_narrative_segments_root_to_cursor_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("# test\n\n[section:ch1]: #\n\nRoot content.")
            _write_node(node.narrative_root / "ch1" / "_node.md",
                "# ch1\n\n[write\n  prompt: x\n]: #\n\nChild content.")
            _commit(root)
            r = crawl(node.child_node("ch1"))
            self.assertEqual(len(r.previous_summaries), 1)
            self.assertIn("Root content", r.previous_summaries[0])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Child content", r.current_content)
            self.assertNotIn("[write", r.current_content)
            self.assertNotIn("[section", r.previous_summaries[0])

    def test_three_levels_root_to_leaf(self) -> None:
        """Root → chapter → scene: crawling from the leaf yields all three segments."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text(
                "# campaign\n\n[section:ch1]: #\n\nCampaign overview."
            )
            _write_node(node.narrative_root / "ch1" / "_node.md",
                "# ch1\n\n[section:scene1]: #\n\nChapter one summary.")
            _write_node(node.narrative_root / "ch1" / "scene1" / "_node.md",
                "# scene1\n\nScene one prose.")
            _commit(root)
            leaf = node.child_node("ch1").child_node("scene1")
            r = crawl(leaf)
            self.assertEqual(len(r.previous_summaries), 2)
            self.assertIn("Campaign overview", r.previous_summaries[0])
            self.assertIn("Chapter one", r.previous_summaries[1])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Scene one prose", r.current_content)

    def test_crawl_from_middle_node_excludes_deeper_children(self) -> None:
        """Crawling from a mid-tree node only includes root and that node, not its children."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("# campaign\n\nCampaign text.")
            _write_node(node.narrative_root / "ch1" / "_node.md",
                "# ch1\n\nChapter text.")
            _write_node(node.narrative_root / "ch1" / "scene1" / "_node.md",
                "# scene1\n\nScene text.")
            _commit(root)
            mid = node.child_node("ch1")
            r = crawl(mid)
            self.assertEqual(len(r.previous_summaries), 1)
            self.assertIn("Campaign text", r.previous_summaries[0])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Chapter text", r.current_content)
            all_text = "\n".join(r.previous_summaries) + (r.current_content or "")
            self.assertNotIn("Scene text", all_text)

    def test_crawl_from_root_only_has_one_segment(self) -> None:
        """Crawling from the root node yields only the root segment."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("# campaign\n\nRoot only.")
            _write_node(node.narrative_root / "ch1" / "_node.md", "# ch1\n\nChild text.")
            _commit(root)
            r = crawl(node)
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Root only", r.current_content)

    def test_comments_stripped_at_all_levels(self) -> None:
        """Front matter, section tags, and write annotations are all stripped across levels."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text(
                "[\n  kb_pin: []\n]: #\n\n# campaign\n\n[section:ch1]: #\n\nRoot text."
            )
            _write_node(node.narrative_root / "ch1" / "_node.md",
                "[\n  kb_pin: []\n]: #\n\n# ch1\n\n[write]: #\n\nChild text.\n\n[/write]: #")
            _commit(root)
            r = crawl(node.child_node("ch1"))
            all_segs = r.previous_summaries + ([r.current_content] if r.current_content else [])
            for seg in all_segs:
                self.assertNotIn("]: #", seg)
                self.assertNotIn("kb_pin", seg)
            self.assertEqual(len(r.previous_summaries), 1)
            self.assertIn("Root text", r.previous_summaries[0])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Child text", r.current_content)

    def test_open_cursor_annotation_at_tail_stripped(self) -> None:
        """An unclosed section annotation at the end (the cursor marker) is stripped."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text(
                "# campaign\n\nRoot text.\n\n[section:ch1]: #\n"
            )
            _commit(root)
            r = crawl(node)
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Root text", r.current_content)
            self.assertNotIn("[section", r.current_content)

    def test_empty_nodes_skipped(self) -> None:
        """Nodes whose content is entirely comments/whitespace do not produce a segment."""
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("[\n  kb_pin: []\n]: #\n")
            _write_node(node.narrative_root / "ch1" / "_node.md", "# ch1\n\nChild text.")
            _commit(root)
            r = crawl(node.child_node("ch1"))
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNotNone(r.current_content)
            assert r.current_content is not None
            self.assertIn("Child text", r.current_content)

    def test_include_narrative_false_skips_narrative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            node.md_path().write_text("# campaign\n\nSome text.")
            _commit(root)
            r = crawl(node, include_narrative=False)
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNone(r.current_content)


class TestCrawlMissingKb(unittest.TestCase):
    def test_missing_objects_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "place", "a", "Place A")
            md = node.md_path()
            md.write_text("[\n  kb_pin:\n    - place.a\n    - place.nonexistent\n]: #\n\n# test\n")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "fm"], cwd=root, capture_output=True, check=True)
            r = crawl(node)
            self.assertEqual(len(r.knowledge), 1)
            self.assertIn("place.a", r.knowledge[0])


class TestAssemblePrompt(unittest.TestCase):
    def test_returns_system_and_user_messages(self) -> None:
        result = CrawlResult(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt(
            result,
            system_prompt="You are helpful.",
            instruction="Do the task.",
        )
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[0]["content"], "You are helpful." + SYSTEM_PROMPT_FORMATTING_ADDENDUM)
        self.assertEqual(msgs[1]["role"], "user")
        self.assertIn("TASK", msgs[1]["content"])
        self.assertIn("Do the task.", msgs[1]["content"])

    def test_omits_kb_block_when_empty(self) -> None:
        result = CrawlResult(knowledge=[], previous_summaries=[], current_content="# test")
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Task",
        )
        self.assertNotIn("KNOWLEDGE", msgs[1]["content"])

    def test_omits_narrative_blocks_when_empty(self) -> None:
        result = CrawlResult(knowledge=["KB[place.a]"], previous_summaries=[], current_content=None)
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Task",
        )
        self.assertNotIn("PREVIOUS EVENTS SUMMARY", msgs[1]["content"])
        self.assertNotIn("CURRENT PASSAGE", msgs[1]["content"])

    def test_includes_kb_and_current_passage_when_present(self) -> None:
        result = CrawlResult(
            knowledge=["KB['place.a']\n  content"],
            previous_summaries=[],
            current_content="# test\n\nprose",
        )
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Task",
        )
        content = msgs[1]["content"]
        self.assertIn("KNOWLEDGE", content)
        self.assertIn("CURRENT PASSAGE", content)
        self.assertIn("place.a", content)
        self.assertIn("prose", content)

    def test_previous_summaries_and_current_passage_use_distinct_blocks(self) -> None:
        result = CrawlResult(
            knowledge=[],
            previous_summaries=["Earlier summary."],
            current_content="Current prose.",
        )
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Task",
        )
        content = msgs[1]["content"]
        self.assertIn("PREVIOUS EVENTS SUMMARY", content)
        self.assertIn("CURRENT PASSAGE", content)
        self.assertIn("Earlier summary.", content)
        self.assertIn("Current prose.", content)

    def test_ai_secret_sections_decoded_in_prompt(self) -> None:
        result = CrawlResult(
            knowledge=[],
            previous_summaries=[],
            current_content=(
                "Visible prose.\n\n"
                "<!-- ai:secret:\ngur frperg vf va gur pbagrag\n-->"
            ),
        )
        msgs = assemble_prompt(
            result,
            system_prompt="Sys",
            instruction="Continue.",
        )
        content = msgs[1]["content"]
        self.assertIn("the secret is in the content", content)
        self.assertIn("<!-- ai:secret:", content)
        self.assertNotIn("gur frperg vf va gur pbagrag", content)


class TestCrawlResultFromPins(unittest.TestCase):
    def test_empty_pins_returns_empty_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            r = crawl_result_from_pins(root, [], [])
            self.assertEqual(r.knowledge, [])
            self.assertEqual(r.previous_summaries, [])
            self.assertIsNone(r.current_content)

    def test_pins_resolved_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "Amy is a hero.")
            r = crawl_result_from_pins(root, ["person.amy"], [])
            self.assertEqual(len(r.knowledge), 1)
            self.assertIn("person.amy", r.knowledge[0])
            self.assertIn("Amy is a hero", r.knowledge[0])

    def test_unpin_excludes_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "Amy")
            _add_kb(root, "place", "x", "Place X")
            r = crawl_result_from_pins(root, ["person.amy", "place.x"], ["place.x"])
            self.assertEqual(len(r.knowledge), 1)
            self.assertIn("person.amy", r.knowledge[0])
            self.assertNotIn("place.x", r.knowledge[0])

    def test_linked_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _node = _make_project(_init_repo(Path(tmp)))
            _add_kb(root, "person", "amy", "Amy")
            _add_kb(root, "place", "market", "The market")
            from lens.core.knowledge import KnowledgeStore
            kb = KnowledgeStore.for_project(root)
            kb.add_tags("person.amy", ["place.market"])
            r = crawl_result_from_pins(root, ["person.amy!"], [])
            self.assertGreaterEqual(len(r.knowledge), 1)
            ids_found = [s for s in r.knowledge if "person.amy" in s or "place.market" in s]
            self.assertGreater(len(ids_found), 0)


class TestAssemblePromptKbEdit(unittest.TestCase):
    def test_new_item_includes_template_when_provided(self) -> None:
        result = CrawlResult(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt_kb_edit(
            result,
            "Create a person",
            existing_content=None,
            template_content="Name:\nDescription:",
            include_template=False,
        )
        self.assertIn("RESULT TEMPLATE", msgs[1]["content"])
        self.assertIn("Name:", msgs[1]["content"])

    def test_existing_item_excludes_template_without_flag(self) -> None:
        result = CrawlResult(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt_kb_edit(
            result,
            "Update the description",
            existing_content="Old content",
            template_content="Template here",
            include_template=False,
        )
        self.assertNotIn("RESULT TEMPLATE", msgs[1]["content"])
        self.assertIn("CURRENT TEXT", msgs[1]["content"])

    def test_existing_item_includes_template_with_flag(self) -> None:
        result = CrawlResult(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt_kb_edit(
            result,
            "Edit",
            existing_content="Current",
            template_content="Template",
            include_template=True,
        )
        self.assertIn("RESULT TEMPLATE", msgs[1]["content"])
        self.assertIn("CURRENT TEXT", msgs[1]["content"])

    def test_crawl_sections_preserved(self) -> None:
        result = CrawlResult(
            knowledge=["KB['x']\n  data"],
            previous_summaries=["Summary"],
            current_content="Passage",
        )
        msgs = assemble_prompt_kb_edit(result, "Edit", existing_content="Item")
        content = msgs[1]["content"]
        self.assertIn("RELEVANT KNOWLEDGE", content)
        self.assertIn("PREVIOUS EVENTS SUMMARY", content)
        self.assertIn("CURRENT PASSAGE", content)
        self.assertIn("Summary", content)
        self.assertIn("Passage", content)

    def test_current_kb_item_block_when_existing(self) -> None:
        result = CrawlResult(knowledge=[], previous_summaries=[], current_content=None)
        msgs = assemble_prompt_kb_edit(
            result,
            "Edit",
            existing_content="Existing KB content",
            template_content=None,
            include_template=False,
        )
        self.assertIn("CURRENT TEXT", msgs[1]["content"])
        self.assertIn("Existing KB content", msgs[1]["content"])

    def test_decodes_secrets_in_user_content(self) -> None:
        result = CrawlResult(
            knowledge=["KB['x']\n  <!-- ai:secret:\ngur frperg\n-->"],
            previous_summaries=[],
            current_content=None,
        )
        msgs = assemble_prompt_kb_edit(result, "Edit", existing_content="X")
        content = msgs[1]["content"]
        self.assertIn("the secret", content)
        self.assertNotIn("gur frperg", content)
