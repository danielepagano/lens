"""Tests for DesignOperator."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.annotations import parse_front_matter
from lens.core.annotations import parse_annotations
from lens.core.llm import FinalPayload, StreamEvent
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.design import DesignOperator
from lens.core.operators.session import prompt_to_slug
from lens.core.project import ProjectSession
from lens.core.storage import Storage


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
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp


def _make_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True,
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


KB_BLOCK = """\
```kb
---
id: npc.testperson
tags:
  - npc
---
A test NPC.
```"""

_FAKE_CONTENT = f"Here are my proposals:\n\n{KB_BLOCK}\n"


async def _fake_generate_stream(*args: Any, **kwargs: Any) -> AsyncIterator[StreamEvent]:
    yield StreamEvent(preview="Here are")
    yield StreamEvent(preview=" my proposals...")
    yield StreamEvent(
        final=FinalPayload(
            text=_FAKE_CONTENT,
            tool_calls=[],
            usage=None,
            interrupted=False,
        )
    )


async def _fake_generate_empty(*args: Any, **kwargs: Any) -> AsyncIterator[StreamEvent]:
    yield StreamEvent(
        final=FinalPayload(
            text="",
            tool_calls=[],
            usage=None,
            interrupted=False,
        )
    )


def _run_design(
    root: Path,
    narrative: NarrativeNode,
    *,
    prompt: str | None = None,
    module_id: str | None = None,
    retry: bool = False,
    end: bool = False,
    generate_mock: Any = None,
) -> Any:
    mock = generate_mock or _fake_generate_stream
    with patch("lens.core.operators.design.generate_stream", new=mock):
        with patch("lens.core.operators.design.get_command_registry", return_value={}):
            return asyncio.run(
                DesignOperator.run_design(
                    session=ProjectSession(root, root),
                    narrative=narrative,
                    prompt=prompt,
                    module_id=module_id,
                    pins=[],
                    unpins=[],
                    retry=retry,
                    end=end,
                )
            )


# ---------------------------------------------------------------------------
# Slug and ID generation
# ---------------------------------------------------------------------------


class TestDesignIdGeneration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._root, self._narrative = _make_project(_init_repo(Path(self._tmp)))

    def _parent(self) -> NarrativeNode:
        return self._narrative.find_cursor()

    def test_no_prompt_no_module(self) -> None:
        self.assertEqual(DesignOperator.generate_session_id(None, None, self._parent()), "design")

    def test_prompt_only(self) -> None:
        result = DesignOperator.generate_session_id("create a tavern now", None, self._parent())
        self.assertEqual(result, "design-create-a-tavern-now")

    def test_prompt_truncated_to_5_words(self) -> None:
        result = DesignOperator.generate_session_id("one two three four five six seven", None, self._parent())
        self.assertEqual(result, "design-one-two-three-four-five")

    def test_module_only(self) -> None:
        result = DesignOperator.generate_session_id(None, "encounter", self._parent())
        self.assertEqual(result, "design-encounter")

    def test_module_and_prompt(self) -> None:
        result = DesignOperator.generate_session_id("tavern scene", "location", self._parent())
        self.assertEqual(result, "design-location-tavern-scene")

    def test_collision_adds_numeric_suffix(self) -> None:
        # Create the base name as an existing child.
        parent = self._parent()
        (parent.md_path().parent / "design.md").write_text("")
        result = DesignOperator.generate_session_id(None, None, parent)
        self.assertEqual(result, "design-1")

    def test_multiple_collisions(self) -> None:
        parent = self._parent()
        folder = parent.md_path().parent
        (folder / "design.md").write_text("")
        (folder / "design-1.md").write_text("")
        result = DesignOperator.generate_session_id(None, None, parent)
        self.assertEqual(result, "design-2")

    def test_prompt_slug_strips_special_chars(self) -> None:
        self.assertEqual(prompt_to_slug("tavern, with — dwarves!"), "tavern-with-dwarves")

    def test_prompt_slug_lowercased(self) -> None:
        self.assertEqual(prompt_to_slug("Tavern With Dwarves"), "tavern-with-dwarves")


# ---------------------------------------------------------------------------
# Fresh run
# ---------------------------------------------------------------------------


class TestDesignFreshRun(unittest.TestCase):
    def test_subnode_file_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative)

            cursor = narrative.find_cursor()
            # cursor should now be inside the design sub-node
            self.assertTrue(cursor.key_path)
            child_md = cursor.md_path()
            self.assertTrue(child_md.exists())

    def test_auto_id_starts_with_design(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative)

            cursor = narrative.find_cursor()
            self.assertTrue(cursor.key_path[-1].startswith("design"))

    def test_open_tag_in_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative)

            cursor = narrative.find_cursor()
            parent = NarrativeNode(
                narrative_root=narrative.narrative_root,
                key_path=cursor.key_path[:-1],
            )
            parent_text = parent.md_path().read_text()
            self.assertIn("[design:", parent_text)

    def test_no_close_tag_after_one_round(self) -> None:
        """Design session stays open after one generation; close tag only on --end."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, prompt="mydesign")

            cursor = narrative.find_cursor()
            parent = NarrativeNode(
                narrative_root=narrative.narrative_root,
                key_path=cursor.key_path[:-1],
            )
            parent_text = parent.md_path().read_text()
            design_id = cursor.key_path[-1]
            self.assertIn(f"[design:{design_id}]: #", parent_text)
            self.assertNotIn(f"[/design:{design_id}]: #", parent_text)

    def test_generated_content_in_subnode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative)

            cursor = narrative.find_cursor()
            child_text = cursor.md_path().read_text()
            self.assertIn("my proposals", child_text)

    def test_inline_block_open_and_close_tags(self) -> None:
        """Child node must contain an inline [design…]: # … [/design]: # block."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative)

            cursor = narrative.find_cursor()
            child_text = cursor.md_path().read_text()
            self.assertIn("[design", child_text)
            self.assertIn("[/design]: #", child_text)

    def test_transaction_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative)

            self.assertTrue(Storage(root).has_pending())

    def test_id_uses_prompt_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, prompt="create a tavern scene")

            cursor = narrative.find_cursor()
            self.assertIn("create-a-tavern-scene", cursor.key_path[-1])

    def test_kb_objects_not_inserted_until_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            run_result = _run_design(root, narrative)
            self.assertEqual(run_result.inserted, [])


# ---------------------------------------------------------------------------
# Module pinning
# ---------------------------------------------------------------------------


class TestDesignModulePin(unittest.TestCase):
    def test_module_pinned_in_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "design").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "design" / "encounter.md").write_text(
                "[DESIGN MODULE]: ENCOUNTER\n", encoding="utf-8"
            )

            _run_design(root, narrative, module_id="encounter")

            cursor = narrative.find_cursor()
            fm = parse_front_matter(cursor.md_path().read_text())
            self.assertIn("design.encounter", fm.get("kb_pin", []))

    def test_missing_module_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            with self.assertRaises(OperatorError) as ctx:
                _run_design(root, narrative, module_id="missing")

            self.assertIn("module does not exist", str(ctx.exception))

    def test_module_in_instruction_context(self) -> None:
        """The module KB object is loaded in RELEVANT KNOWLEDGE (via front matter pin)."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "design").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "design" / "encounter.md").write_text(
                "[DESIGN MODULE]: ENCOUNTER\n\nDo X then Y.\n", encoding="utf-8"
            )

            captured: list[list[dict[str, str]]] = []

            async def _capture_stream(*args: Any, **kwargs: Any) -> AsyncIterator[StreamEvent]:
                captured.append(args[0])
                async for ev in _fake_generate_stream(*args, **kwargs):
                    yield ev

            _run_design(root, narrative, module_id="encounter", generate_mock=_capture_stream)

            self.assertEqual(len(captured), 1)
            # The module text should appear somewhere in the messages
            full_content = " ".join(str(m) for m in captured[0])
            self.assertIn("encounter", full_content.lower())


class TestDesignCompanionTemplatePin(unittest.TestCase):
    def test_pins_type_template_when_kb_has_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "design").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "design" / "location.md").write_text(
                "[DESIGN MODULE]: LOCATION\n", encoding="utf-8"
            )
            (root / "knowledge" / "location").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "location" / "_template.md").write_text(
                "TEMPLATE\n", encoding="utf-8"
            )

            _run_design(root, narrative, module_id="location")

            cursor = narrative.find_cursor()
            fm = parse_front_matter(cursor.md_path().read_text())
            pins = fm.get("kb_pin", [])
            self.assertIn("design.location", pins)
            self.assertIn("location._template", pins)

    def test_no_template_pin_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "design").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "design" / "world.md").write_text(
                "[DESIGN MODULE]: WORLD\n", encoding="utf-8"
            )

            _run_design(root, narrative, module_id="world")

            cursor = narrative.find_cursor()
            fm = parse_front_matter(cursor.md_path().read_text())
            pins = fm.get("kb_pin", [])
            self.assertIn("design.world", pins)
            self.assertNotIn("world._template", pins)

    def test_module_switch_replaces_template_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "design").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "design" / "encounter.md").write_text("E\n")
            (root / "knowledge" / "design" / "npc.md").write_text("N\n")
            for t in ("encounter", "npc"):
                (root / "knowledge" / t).mkdir(parents=True, exist_ok=True)
                (root / "knowledge" / t / "_template.md").write_text(f"{t}\n")

            _run_design(root, narrative, module_id="encounter")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "first"], cwd=root, capture_output=True, check=True,
            )

            _run_design(root, narrative, module_id="npc")

            cursor = narrative.find_cursor()
            fm = parse_front_matter(cursor.md_path().read_text())
            pins = fm.get("kb_pin", [])
            self.assertIn("design.npc", pins)
            self.assertIn("npc._template", pins)
            self.assertNotIn("design.encounter", pins)
            self.assertNotIn("encounter._template", pins)


# ---------------------------------------------------------------------------
# Continue run (second call inside the same design session)
# ---------------------------------------------------------------------------


class TestDesignContinueRun(unittest.TestCase):
    def test_second_call_adds_inline_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, prompt="first round")
            # Commit so second call sees a clean state.
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "first"], cwd=root, capture_output=True, check=True,
            )

            _run_design(root, narrative, prompt="second round")

            cursor = narrative.find_cursor()
            child_text = cursor.md_path().read_text()
            # Both rounds' content should appear
            self.assertEqual(child_text.count("[/design]: #"), 2)

    def test_second_call_crawls_design_child(self) -> None:
        """Crawl must receive the design sub-node so CURRENT PASSAGE is the conversation."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, prompt="first round")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "first"], cwd=root, capture_output=True, check=True,
            )

            crawl_called_with_node: list[NarrativeNode] = []

            def capture_crawl(node: NarrativeNode, **kwargs: Any) -> Any:
                crawl_called_with_node.append(node)
                from lens.core.context import crawl as real_crawl
                return real_crawl(node, **kwargs)

            with patch("lens.core.operators.design.generate_stream", new=_fake_generate_stream):
                with patch("lens.core.operators.design.get_command_registry", return_value={}):
                    with patch("lens.core.operators.design.crawl", side_effect=capture_crawl):
                        asyncio.run(
                            DesignOperator.run_design(
                                session=ProjectSession(root, root),
                                narrative=narrative,
                                prompt="second round",
                                pins=[],
                                unpins=[],
                            )
                        )

            self.assertGreater(len(crawl_called_with_node), 0)
            node_used = crawl_called_with_node[0]
            # The crawled node should be the design sub-node
            self.assertGreater(len(node_used.key_path), 0)
            self.assertTrue(node_used.key_path[-1].startswith("design"))


# ---------------------------------------------------------------------------
# Module switching
# ---------------------------------------------------------------------------


class TestDesignModuleSwitch(unittest.TestCase):
    def test_switch_module_replaces_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "design").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "design" / "encounter.md").write_text("E\n")
            (root / "knowledge" / "design" / "npc.md").write_text("N\n")

            _run_design(root, narrative, module_id="encounter")
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "first"], cwd=root, capture_output=True, check=True,
            )

            _run_design(root, narrative, module_id="npc")

            cursor = narrative.find_cursor()
            fm = parse_front_matter(cursor.md_path().read_text())
            kb_pins = fm.get("kb_pin", [])
            self.assertIn("design.npc", kb_pins)
            self.assertNotIn("design.encounter", kb_pins)


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


class TestDesignRetry(unittest.TestCase):
    def test_retry_requires_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative)
            # Commit everything first → no pending
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "done"], cwd=root, capture_output=True, check=True,
            )

            with self.assertRaises(OperatorError) as ctx:
                _run_design(root, narrative, retry=True)

            self.assertIn("no pending design transaction", str(ctx.exception))

    def test_retry_rewrites_last_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, prompt="first")

            cursor = narrative.find_cursor()
            original_text = cursor.md_path().read_text()
            self.assertIn("my proposals", original_text)

            async def _different_content(*args: Any, **kwargs: Any) -> AsyncIterator[StreamEvent]:
                yield StreamEvent(
                    final=FinalPayload(
                        text="Completely different content.",
                        tool_calls=[],
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_design(root, narrative, retry=True, generate_mock=_different_content)

            cursor2 = narrative.find_cursor()
            retried_text = cursor2.md_path().read_text()
            self.assertIn("Completely different content.", retried_text)
            # Original content should be gone
            self.assertNotIn("my proposals", retried_text)


# ---------------------------------------------------------------------------
# Design end
# ---------------------------------------------------------------------------


class TestDesignEnd(unittest.TestCase):
    def test_end_appends_close_tag_and_runs_kb_extract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _run_design(root, narrative)

            cursor = narrative.find_cursor()
            design_id = cursor.key_path[-1]
            parent = NarrativeNode(
                narrative_root=narrative.narrative_root, key_path=cursor.key_path[:-1]
            )
            before = parent.md_path().read_text()
            self.assertIn(f"[design:{design_id}]: #", before)
            self.assertNotIn(f"[/design:{design_id}]: #", before)

            result = asyncio.run(
                DesignOperator.run_session_end(
                    session=ProjectSession(root, root), narrative=narrative
                )
            )

            after = parent.md_path().read_text()
            self.assertIn(f"[/design:{design_id}]: #", after)
            open_pos = after.index(f"[design:{design_id}]: #")
            close_pos = after.index(f"[/design:{design_id}]: #")
            self.assertLess(open_pos, close_pos)
            # KB block from fake content must be extracted
            self.assertIn("npc.testperson", result.inserted)

    def test_end_raises_when_cursor_not_in_design(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            with self.assertRaises(OperatorError) as ctx:
                asyncio.run(
                    DesignOperator.run_session_end(
                        session=ProjectSession(root, root), narrative=narrative
                    )
                )
            self.assertIn("no open design to close", str(ctx.exception))

    def test_end_via_run_session_end_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _run_design(root, narrative)

            result = _run_design(root, narrative, end=True)
            self.assertIn("npc.testperson", result.inserted)


# ---------------------------------------------------------------------------
# @ mention expansion
# ---------------------------------------------------------------------------


class TestDesignMentionExpansion(unittest.TestCase):
    def test_mention_in_fresh_prompt_pins_kb_object(self) -> None:
        """@type.key mentions in prompts must be stored on the operator annotation (not node front matter)."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "npc").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "npc" / "smith.md").write_text("A blacksmith NPC.\n")

            _run_design(root, narrative, prompt="Design @npc.smith as a quest giver")

            cursor = narrative.find_cursor()
            text = cursor.md_path().read_text(encoding="utf-8")
            fm = parse_front_matter(text)
            self.assertNotIn("npc.smith", fm.get("kb_pin", []))
            anns = [a for a in parse_annotations(text) if a.operator == "design" and not a.closing]
            self.assertTrue(anns)
            self.assertIn("npc.smith", anns[-1].params.get("kb_pin", []))

    def test_mention_in_continuation_prompt_pins_kb_object(self) -> None:
        """@type.key mentions in continuation prompts must be stored on the operator annotation (not node front matter)."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            (root / "knowledge" / "npc").mkdir(parents=True, exist_ok=True)
            (root / "knowledge" / "npc" / "smith.md").write_text("A blacksmith NPC.\n")

            # First call to start the session.
            _run_design(root, narrative)

            # Second call (continuation) with mention in prompt.
            _run_design(root, narrative, prompt="Continue with @npc.smith")

            cursor = narrative.find_cursor()
            text = cursor.md_path().read_text(encoding="utf-8")
            fm = parse_front_matter(text)
            self.assertNotIn("npc.smith", fm.get("kb_pin", []))
            anns = [a for a in parse_annotations(text) if a.operator == "design" and not a.closing]
            self.assertTrue(anns)
            self.assertIn("npc.smith", anns[-1].params.get("kb_pin", []))

    def test_nonexistent_mention_not_pinned(self) -> None:
        """@ mentions for KB objects that don't exist must not be pinned."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, prompt="Design @npc.ghost who does not exist")

            cursor = narrative.find_cursor()
            fm = parse_front_matter(cursor.md_path().read_text(encoding="utf-8"))
            self.assertNotIn("npc.ghost", fm.get("kb_pin", []))


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestDesignErrors(unittest.TestCase):
    def test_empty_generation_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            with self.assertRaises(OperatorError) as ctx:
                _run_design(root, narrative, generate_mock=_fake_generate_empty)

            self.assertIn("no content generated", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
