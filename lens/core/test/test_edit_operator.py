"""Unit and integration tests for EditOperator."""

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

from lens.core.llm import FinalPayload, StreamEvent
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.edit import EditOperator
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


def _commit_node_content(root: Path, node: NarrativeNode, content: str) -> None:
    node.md_path().write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "content"], cwd=root, capture_output=True, check=True,
    )


async def _fake_generate_stream(*args: Any, **kwargs: Any) -> Any:
    for chunk in ["Generated", " content"]:
        yield StreamEvent(preview=chunk)
    yield StreamEvent(
        final=FinalPayload(
            text="Generated content",
            tool_calls=[],
            usage=None,
            interrupted=False,
        )
    )


def _run_mutation(
    root: Path,
    node: NarrativeNode,
    rel_path: str,
    ann_id: str,
    start_line: int,
    end_line: int,
    *,
    prompt: str | None = None,
    retry: bool = False,
    generate_mock: Any = None,
    manual: bool = False,
) -> None:
    mock = generate_mock or _fake_generate_stream
    with patch("lens.core.operator.generate_stream", new=mock):
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()):
                asyncio.run(
                    EditOperator.run_mutation(
                        session=ProjectSession(root, root),
                        node=node,
                        rel_path=rel_path,
                        ann_id=ann_id,
                        start_line=start_line,
                        end_line=end_line,
                        prompt=prompt,
                        manual=manual,
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=retry,
                    )
                )


# ---------------------------------------------------------------------------
# build_instruction
# ---------------------------------------------------------------------------

class TestEditOperatorBuildInstruction(unittest.TestCase):
    def test_build_instruction_with_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = EditOperator(Storage(root), narrative)
            result = op.build_instruction({"prompt": "make it darker"})
            self.assertIn("make it darker", result)


# ---------------------------------------------------------------------------
# run_mutation integration tests
# ---------------------------------------------------------------------------

class TestEditOperatorRunMutation(unittest.TestCase):

    _REL_PATH = "narrative/test/_node.md"

    def test_run_mutation_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Original line one.\nOriginal line two.\n")

            _run_mutation(root, narrative, self._REL_PATH, "e1_1", 1, 1, prompt="rewrite it")

            self.assertTrue(Storage(root).has_pending())
            text = narrative.md_path().read_text()
            self.assertIn("Generated content", text)
            self.assertNotIn("Original line one.", text)
            self.assertNotIn("[edit:e1_1]: #", text)

    def test_run_mutation_fresh_stores_prompt_in_claim(self) -> None:
        """The prompt is stored in the staged claim tag for recovery on retry."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Original line one.\nOriginal line two.\n")

            _run_mutation(root, narrative, self._REL_PATH, "e1_1", 1, 1, prompt="be poetic")

            # The claim is staged — check the index content via git show
            result = __import__("subprocess").run(
                ["git", "show", f":{self._REL_PATH}"],
                cwd=root, capture_output=True, text=True,
            )
            self.assertIn("be poetic", result.stdout)

    def test_run_mutation_fresh_preserves_other_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Line one.\nLine two.\nLine three.\n")

            _run_mutation(root, narrative, self._REL_PATH, "e2_2", 2, 2, prompt="punch it up")

            text = narrative.md_path().read_text()
            self.assertIn("Generated content", text)
            self.assertIn("Line three.", text)

    def test_run_mutation_fresh_no_prompt_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Some content.\n")

            with self.assertRaises(OperatorError):
                asyncio.run(
                    EditOperator.run_mutation(
                        session=ProjectSession(root, root),
                        node=narrative,
                        rel_path=self._REL_PATH,
                        ann_id="e1_1",
                        start_line=1,
                        end_line=1,
                        prompt=None,
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=False,
                    )
                )

    def test_run_mutation_retry_reuses_stored_prompt(self) -> None:
        """Retry without a new prompt recovers the prompt from the claim tag."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Original line one.\nOriginal line two.\n")

            _run_mutation(root, narrative, self._REL_PATH, "e1_1", 1, 1, prompt="be poetic")

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

            # No prompt supplied — should recover from the claim tag
            _run_mutation(
                root, narrative, self._REL_PATH, "e1_1", 1, 1,
                retry=True, generate_mock=_retry,
            )

            text = narrative.md_path().read_text()
            self.assertIn("Retried content", text)
            self.assertNotIn("Generated content", text)
            self.assertTrue(Storage(root).has_pending())

    def test_run_mutation_retry_with_new_prompt(self) -> None:
        """Retry with a new prompt overrides the stored one."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Original line one.\nOriginal line two.\n")

            _run_mutation(root, narrative, self._REL_PATH, "e1_1", 1, 1, prompt="be poetic")

            async def _retry(*args: Any, **kwargs: Any) -> Any:
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

            _run_mutation(
                root, narrative, self._REL_PATH, "e1_1", 1, 1,
                retry=True, prompt="be dramatic", generate_mock=_retry,
            )

            text = narrative.md_path().read_text()
            self.assertIn("Updated content", text)

    def test_run_mutation_range_has_annotation_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "[section:ch1]: #\nSome content.\n")

            with self.assertRaises(OperatorError):
                asyncio.run(
                    EditOperator.run_mutation(
                        session=ProjectSession(root, root),
                        node=narrative,
                        rel_path=self._REL_PATH,
                        ann_id="e1_1",
                        start_line=1,
                        end_line=1,
                        prompt="fix it",
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=False,
                    )
                )

    def test_run_mutation_retry_no_pending_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Some content.\n")

            with self.assertRaises(OperatorError):
                asyncio.run(
                    EditOperator.run_mutation(
                        session=ProjectSession(root, root),
                        node=narrative,
                        rel_path=self._REL_PATH,
                        ann_id="e1_1",
                        start_line=1,
                        end_line=1,
                        prompt=None,
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=True,
                    )
                )

    def test_run_mutation_manual_replace_replaces_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Original line one.\nOriginal line two.\n")

            _run_mutation(
                root,
                narrative,
                self._REL_PATH,
                "e1_1",
                1,
                1,
                prompt="Manual replacement",
                manual=True,
            )

            text = narrative.md_path().read_text()
            self.assertIn("Manual replacement", text)
            self.assertNotIn("Original line one.", text)
            self.assertNotIn("[edit:e1_1]: #", text)
            self.assertFalse(
                text.startswith("\n"),
                "replace from line 1 must not prepend a spurious blank line",
            )

    def test_run_mutation_manual_replace_stores_params_in_claim(self) -> None:
        """Manual replace stores manual flag and prompt in the claim tag."""
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            _commit_node_content(root, narrative, "Original line one.\nOriginal line two.\n")

            _run_mutation(
                root,
                narrative,
                self._REL_PATH,
                "e1_1",
                1,
                1,
                prompt="Some long replacement text",
                manual=True,
            )

            result = __import__("subprocess").run(
                ["git", "show", f":{self._REL_PATH}"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertIn("manual: true", result.stdout)
            self.assertIn("prompt: Some long replacement text", result.stdout)
