"""Unit and integration tests for WriteOperator."""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.context import CrawlResult
from lens.core.llm import FinalPayload, StreamEvent
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.write import WriteOperator
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


async def _fake_generate_stream(*args: Any, **kwargs: Any) -> Any:
    for chunk in ["Generated", " content"]:
        yield StreamEvent(preview=chunk)
    yield StreamEvent(
        final=FinalPayload(
            text="Generated content",
            tool_call=None,
            usage=None,
            interrupted=False,
        )
    )


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
    mock = generate_mock or _fake_generate_stream
    with patch("lens.core.operator.generate_stream", new=mock):
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
            self.assertIn("story-writing", messages[0]["content"])
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
            self.assertIn("steps: 1", text)
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

    def test_run_inline_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            node_file = narrative.find_cursor().md_path()

            _run_inline(root, narrative)

            async def _second(*args: Any, **kwargs: Any) -> Any:
                for chunk in ["More", " text"]:
                    yield StreamEvent(preview=chunk)
                yield StreamEvent(
                    final=FinalPayload(
                        text="More text",
                        tool_call=None,
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_inline(root, narrative, generate_mock=_second)

            text = node_file.read_text()
            self.assertIn("steps: 2", text)
            self.assertIn("Generated content", text)
            self.assertIn("More text", text)
            self.assertIn("[/write]: #", text)
            # Only one close tag
            self.assertEqual(text.count("[/write]: #"), 1)
            # Both batches precede the close tag
            close_pos = text.index("[/write]: #")
            self.assertLess(text.index("Generated content"), close_pos)
            self.assertLess(text.index("More text"), close_pos)

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
                        tool_call=None,
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_inline(root, narrative, retry=True, generate_mock=_retry)

            text = node_file.read_text()
            self.assertIn("Retried content", text)
            self.assertNotIn("Generated content", text)
            self.assertIn("steps: 1", text)
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
                        tool_call=None,
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

    def test_run_inline_retry_with_new_prompt(self) -> None:
        """--retry with a new prompt discards the pending result and regenerates."""
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
                        tool_call=None,
                        usage=None,
                        interrupted=False,
                    )
                )

            _run_inline(root, narrative, retry=True, prompt="new direction", generate_mock=_updated)

            text = node_file.read_text()
            self.assertIn("Updated content", text)
            self.assertIn("new direction", text)
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
