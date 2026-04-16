"""Unit and integration tests for WriteOperator."""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from collections.abc import Awaitable, Callable

from lens.core.annotations import parse_annotations, parse_front_matter
from lens.core.context import CrawlResult
from lens.core.knowledge import KnowledgeStore
from lens.core.llm import FinalPayload, StreamEvent
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.write import WriteOperator
from lens.core.prompts import PromptStore
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


async def _fake_generate_text(*args: Any, **kwargs: Any) -> str:
    on_preview = kwargs.get("on_preview")
    if on_preview is not None:
        cb = cast(Callable[[str], Awaitable[None]], on_preview)
        await cb("Generated")
        await cb(" content")
    return "Generated content"


def _run_inline(
    root: Path,
    narrative: NarrativeNode,
    *,
    prompt: str | None = None,
    pins: list[str] | None = None,
    unpins: list[str] | None = None,
    llm_id: str | None = None,
    retry: bool = False,
    generate_mock: Any = None,
) -> None:
    raw_mock = generate_mock or _fake_generate_text

    async def _mock_text(*args: Any, **kwargs: Any) -> str:
        res = raw_mock(*args, **kwargs)
        if hasattr(res, "__aiter__"):
            on_preview = kwargs.get("on_preview")
            cb = cast(Callable[[str], Awaitable[None]] | None, on_preview)
            async for ev in cast(Any, res):
                if getattr(ev, "preview", None) and cb is not None:
                    await cb(cast(str, ev.preview))
                if getattr(ev, "final", None) is not None:
                    return ev.final.text
            return ""
        return await cast(Awaitable[str], res)

    with patch("lens.core.operator.generate_text", new=_mock_text):
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()):
                asyncio.run(
                    WriteOperator.run_inline(
                        session=ProjectSession(root, root),
                        narrative=narrative,
                        prompt=prompt,
                        pins=pins or [],
                        unpins=unpins or [],
                        llm_id=llm_id,
                        retry=retry,
                    )
                )


# ---------------------------------------------------------------------------
# build_instruction
# ---------------------------------------------------------------------------

class TestWriteOperatorBuildInstruction(unittest.TestCase):
    def test_build_instruction_no_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = WriteOperator(Storage(root), narrative)
            self.assertEqual(op.build_instruction({}), "Continue writing.")

    def test_build_instruction_with_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = WriteOperator(Storage(root), narrative)
            result = op.build_instruction({"prompt": "be dramatic"})
            self.assertIn("be dramatic", result)
            self.assertNotEqual(result, "Continue writing.")


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------

class TestWriteOperatorBuildMessages(unittest.TestCase):
    def test_build_messages_assembles_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = WriteOperator(Storage(root), narrative)
            cr = CrawlResult(
                knowledge=[],
                previous_summaries=[],
                current_content="Existing text.",
            )
            messages = op.build_messages(cr, {"prompt": "keep going"})
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["role"], "system")
            prompts = PromptStore(root)
            self.assertEqual(
                messages[0]["content"],
                prompts.get("write.system") + prompts.get("shared.formatting_addendum"),
            )
            user_content = messages[1]["content"]
            self.assertIn("CURRENT PASSAGE", user_content)
            self.assertIn("TASK", user_content)
            self.assertIn("keep going", user_content)

    def test_build_messages_system_prompt_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = WriteOperator(Storage(root), narrative)
            cr = CrawlResult(knowledge=[], previous_summaries=[], current_content=None)
            messages = op.build_messages(cr, {})
            self.assertEqual(messages[0]["role"], "system")
            self.assertGreater(len(messages[0]["content"]), 0)


# ---------------------------------------------------------------------------
# run_inline integration tests
# ---------------------------------------------------------------------------

class TestWriteOperatorRunInline(unittest.TestCase):
    def test_run_inline_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            node_file = narrative.find_cursor().md_path()

            _run_inline(root, narrative)

            text = node_file.read_text()
            self.assertIn("[write", text)
            self.assertIn("Generated content", text)
            self.assertIn("[/write]: #", text)
            self.assertTrue(Storage(root).has_pending())

    def test_run_inline_fresh_close_tag_after_content(self) -> None:
        """The close tag must appear after the generated content, not before."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            node_file = narrative.find_cursor().md_path()

            _run_inline(root, narrative)

            text = node_file.read_text()
            content_pos = text.index("Generated content")
            close_pos = text.index("[/write]: #")
            self.assertLess(content_pos, close_pos)

    def test_run_inline_second_call_requires_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _run_inline(root, narrative)

            async def _second(*args: Any, **kwargs: Any) -> Any:
                for chunk in ["More", " text"]:
                    yield StreamEvent(preview=chunk)
                yield StreamEvent(
                    final=FinalPayload(
                        text="More text",
                        tool_calls=[],
                        usage=None,
                        interrupted=False,
                    )
                )

            with self.assertRaises(OperatorError):
                _run_inline(root, narrative, prompt=None, generate_mock=_second)

    def test_run_inline_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            node_file = narrative.find_cursor().md_path()

            _run_inline(root, narrative)

            async def _retry(*args: Any, **kwargs: Any) -> Any:
                for chunk in ["Retried", " content"]:
                    yield StreamEvent(preview=chunk)
                yield StreamEvent(
                    final=FinalPayload(
                        text="Retried content",
                        tool_calls=[],
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_inline(root, narrative, retry=True, generate_mock=_retry)

            text = node_file.read_text()
            self.assertIn("Retried content", text)
            self.assertNotIn("Generated content", text)
            self.assertIn("[/write]: #", text)
            self.assertLess(text.index("Retried content"), text.index("[/write]: #"))

    def test_run_inline_new_prompt_starts_fresh(self) -> None:
        """New prompt without --retry auto-commits the pending result and starts fresh."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            node_file = narrative.find_cursor().md_path()

            _run_inline(root, narrative, prompt="original direction")

            async def _fresh(*args: Any, **kwargs: Any) -> Any:
                for chunk in ["Fresh", " content"]:
                    yield StreamEvent(preview=chunk)
                yield StreamEvent(
                    final=FinalPayload(
                        text="Fresh content",
                        tool_calls=[],
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_inline(root, narrative, prompt="new direction", generate_mock=_fresh)

            text = node_file.read_text()
            # Both write blocks present: first was committed, second is pending
            self.assertIn("Generated content", text)
            self.assertIn("Fresh content", text)
            self.assertIn("new direction", text)
            # Two separate close tags (one per block)
            self.assertEqual(text.count("[/write]: #"), 2)

    def test_run_inline_retry_with_feedback(self) -> None:
        """--retry with a prompt treats it as feedback: original prompt kept, new content written."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            node_file = narrative.find_cursor().md_path()

            _run_inline(root, narrative, prompt="original direction")

            async def _updated(*args: Any, **kwargs: Any) -> Any:
                for chunk in ["Updated", " content"]:
                    yield StreamEvent(preview=chunk)
                yield StreamEvent(
                    final=FinalPayload(
                        text="Updated content",
                        tool_calls=[],
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_inline(root, narrative, retry=True, prompt="that part was wrong", generate_mock=_updated)

            text = node_file.read_text()
            self.assertIn("Updated content", text)
            # Original prompt stays in the annotation; feedback is NOT stored.
            self.assertIn("original direction", text)
            self.assertNotIn("that part was wrong", text)
            self.assertNotIn("Generated content", text)
            self.assertIn("[/write]: #", text)
            self.assertEqual(text.count("[/write]: #"), 1)
            self.assertLess(text.index("Updated content"), text.index("[/write]: #"))

    def test_run_inline_retry_no_pending_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            with self.assertRaises(OperatorError):
                asyncio.run(
                    WriteOperator.run_inline(
                        session=ProjectSession(root, root),
                        narrative=narrative,
                        prompt=None,
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=True,
                    )
                )

    def test_at_mention_is_persisted_on_write_annotation_and_in_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            KnowledgeStore.clear_registry()
            kb_dir = root / "knowledge" / "person"
            kb_dir.mkdir(parents=True, exist_ok=True)
            (kb_dir / "amy.md").write_text("Amy the merchant.\n", encoding="utf-8")

            async def _assert_prompt_contains_kb(
                messages: list[dict[str, str]], *_args: Any, **_kwargs: Any
            ) -> Any:
                user_content = messages[1]["content"]
                self.assertIn("RELEVANT KNOWLEDGE", user_content)
                self.assertIn("Amy the merchant.", user_content)
                yield StreamEvent(
                    final=FinalPayload(
                        text="Generated content",
                        tool_calls=[],
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_inline(root, narrative, prompt="Write a scene with @person.amy", generate_mock=_assert_prompt_contains_kb)

            text = narrative.find_cursor().md_path().read_text(encoding="utf-8")
            fm = parse_front_matter(text)
            self.assertNotIn("person.amy", fm.get("kb_pin", []))
            anns = [a for a in parse_annotations(text) if a.operator == "write" and not a.closing]
            self.assertTrue(anns)
            self.assertIn("person.amy", anns[-1].params.get("kb_pin", []))

    def test_at_mention_added_on_retry_prompt_updates_annotation_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            KnowledgeStore.clear_registry()
            kb_dir = root / "knowledge" / "person"
            kb_dir.mkdir(parents=True, exist_ok=True)
            (kb_dir / "amy.md").write_text("Amy the merchant.\n", encoding="utf-8")

            _run_inline(root, narrative, prompt="Original direction")

            async def _retry_stream(
                messages: list[dict[str, str]], *_args: Any, **_kwargs: Any
            ) -> Any:
                # Mention appears only on retry prompt; it must be pinned and present in crawl.
                self.assertIn("Amy the merchant.", messages[1]["content"])
                yield StreamEvent(
                    final=FinalPayload(
                        text="Retried content",
                        tool_calls=[],
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_inline(root, narrative, retry=True, prompt="Now include @person.amy", generate_mock=_retry_stream)

            text = narrative.find_cursor().md_path().read_text(encoding="utf-8")
            anns = [a for a in parse_annotations(text) if a.operator == "write" and not a.closing]
            self.assertTrue(anns)
            self.assertIn("person.amy", anns[-1].params.get("kb_pin", []))


class TestWriteManual(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root, self.narrative = _make_project(_init_repo(Path(self.tmp)))
        self.session = ProjectSession(self.root, self.root)

    def _node_content(self) -> str:
        return (self.root / "narrative" / "test" / "_node.md").read_text()

    def test_appends_text_to_cursor(self) -> None:
        """run_manual appends the given text after the existing content."""
        addr = WriteOperator.run_manual(
            session=self.session,
            narrative=self.narrative,
            text="Manually added paragraph.",
        )
        content = self._node_content()
        self.assertIn("Manually added paragraph.", content)
        self.assertTrue(content.startswith("# test"))
        self.assertIsInstance(addr, str)

    def test_no_operator_annotations(self) -> None:
        """run_manual must not add any [write...] annotations."""
        WriteOperator.run_manual(
            session=self.session,
            narrative=self.narrative,
            text="No annotations here.",
        )
        content = self._node_content()
        self.assertNotIn("[write", content)
        self.assertNotIn("]: #", content)

    def test_blank_line_separator(self) -> None:
        """run_manual ensures a blank line between existing content and appended text."""
        WriteOperator.run_manual(
            session=self.session,
            narrative=self.narrative,
            text="New paragraph.",
        )
        content = self._node_content()
        # The original content ends with \n; appended text must be separated
        self.assertIn("\n\nNew paragraph.", content)

    def test_multiple_appends(self) -> None:
        """run_manual can be called multiple times; each append is independent."""
        WriteOperator.run_manual(session=self.session, narrative=self.narrative, text="First.")
        # Stage the first change so we own a fresh transaction for the second
        self.session.new_storage().stage_all()
        WriteOperator.run_manual(session=self.session, narrative=self.narrative, text="Second.")
        content = self._node_content()
        self.assertIn("First.", content)
        self.assertIn("Second.", content)
        idx_first = content.index("First.")
        idx_second = content.index("Second.")
        self.assertLess(idx_first, idx_second)

    def test_returns_cursor_address(self) -> None:
        """run_manual returns the address string of the cursor node."""
        addr = WriteOperator.run_manual(
            session=self.session,
            narrative=self.narrative,
            text="Check address.",
        )
        # Root narrative cursor address is the narrative name with no subpath
        self.assertEqual(addr, "test")
