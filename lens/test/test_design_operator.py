"""Tests for DesignOperator."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.llm import FinalPayload, StreamEvent
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.design import DesignOperator
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


async def _fake_generate_stream(*args: Any, **kwargs: Any) -> Any:
    yield StreamEvent(preview="Here are")
    yield StreamEvent(preview=" my proposals...")
    yield StreamEvent(
        final=FinalPayload(
            text=_FAKE_CONTENT,
            tool_call=None,
            usage=None,
            interrupted=False,
        )
    )


async def _fake_generate_empty(*args: Any, **kwargs: Any) -> Any:
    yield StreamEvent(
        final=FinalPayload(
            text="",
            tool_call=None,
            usage=None,
            interrupted=False,
        )
    )


def _run_design(
    root: Path,
    narrative: NarrativeNode,
    *,
    id: str = "mydesign",
    prompt: str | None = None,
    generate_mock: Any = None,
) -> Any:
    mock = generate_mock or _fake_generate_stream
    with patch("lens.core.operators.design.generate_stream", new=mock):
        with patch("lens.core.operators.design.get_command_registry", return_value={}):
            return asyncio.run(
                DesignOperator.run_design(
                    session=ProjectSession(root, root),
                    narrative=narrative,
                    id=id,
                    prompt=prompt,
                    pins=[],
                    unpins=[],
                )
            )


# ---------------------------------------------------------------------------
# build_instruction
# ---------------------------------------------------------------------------


class TestDesignBuildInstruction(unittest.TestCase):
    def test_no_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = DesignOperator(Storage(root), narrative)
            result = op.build_instruction({})
            self.assertIn("Start the design session", result)

    def test_with_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            op = DesignOperator(Storage(root), narrative)
            result = op.build_instruction({"prompt": "create a tavern"})
            self.assertIn("create a tavern", result)
            self.assertNotIn("Start the design session", result)


# ---------------------------------------------------------------------------
# Fresh run
# ---------------------------------------------------------------------------


class TestDesignFreshRun(unittest.TestCase):
    def test_subnode_file_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, id="mydesign")

            cursor = narrative.find_cursor()
            child_md = cursor.md_path().parent / "mydesign.md"
            self.assertTrue(child_md.exists())

    def test_open_tag_in_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, id="mydesign")

            cursor = narrative.find_cursor()
            parent_text = cursor.md_path().read_text()
            self.assertIn("[design:mydesign]: #", parent_text)

    def test_close_tag_in_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, id="mydesign")

            cursor = narrative.find_cursor()
            parent_text = cursor.md_path().read_text()
            self.assertIn("[/design:mydesign]: #", parent_text)

    def test_open_before_close_in_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, id="mydesign")

            cursor = narrative.find_cursor()
            parent_text = cursor.md_path().read_text()
            open_pos = parent_text.index("[design:mydesign]: #")
            close_pos = parent_text.index("[/design:mydesign]: #")
            self.assertLess(open_pos, close_pos)

    def test_generated_content_in_subnode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, id="mydesign")

            cursor = narrative.find_cursor()
            child_md = cursor.md_path().parent / "mydesign.md"
            child_text = child_md.read_text()
            self.assertIn("my proposals", child_text)

    def test_kb_objects_inserted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            result = _run_design(root, narrative, id="mydesign")

            self.assertIn("npc.testperson", result.inserted)
            self.assertEqual(result.errors, [])

    def test_transaction_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, id="mydesign")

            self.assertTrue(Storage(root).has_pending())


# ---------------------------------------------------------------------------
# Continue run (pending transaction for same id)
# ---------------------------------------------------------------------------


class TestDesignContinueRun(unittest.TestCase):
    def test_continue_appends_to_subnode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            # First run (interrupted — no close tag written yet).
            # Simulate by manually writing the open tag + child file.
            cursor = narrative.find_cursor()
            # Promote to folder manually.
            folder = cursor.md_path().parent
            child_md = folder / "mydesign.md"
            child_md.write_text("First round content.\n")
            parent_text = cursor.md_path().read_text()
            cursor.md_path().write_text(parent_text + "\n[design:mydesign]: #\n")

            # Second generation mock returns different content.
            async def _second_gen(*args: Any, **kwargs: Any) -> Any:
                yield StreamEvent(
                    final=FinalPayload(
                        text="Second round content.",
                        tool_call=None,
                        usage=None,
                        interrupted=False,
                    )
                )

            with patch("lens.core.operators.design.generate_stream", new=_second_gen):
                with patch(
                    "lens.core.operators.design.get_command_registry", return_value={}
                ):
                    asyncio.run(
                        DesignOperator.run_design(
                            session=ProjectSession(root, root),
                            narrative=narrative,
                            id="mydesign",
                            pins=[],
                            unpins=[],
                        )
                    )

            child_text = child_md.read_text()
            self.assertIn("First round content.", child_text)
            self.assertIn("Second round content.", child_text)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestDesignErrors(unittest.TestCase):
    def test_duplicate_committed_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            _run_design(root, narrative, id="mydesign")

            # Commit the pending transaction.
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "design"],
                cwd=root, capture_output=True, check=True,
            )

            with self.assertRaises(OperatorError) as ctx:
                _run_design(root, narrative, id="mydesign")

            self.assertIn("already exists", str(ctx.exception))

    def test_invalid_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            with self.assertRaises(OperatorError) as ctx:
                _run_design(root, narrative, id="bad id!")

            self.assertIn("invalid design id", str(ctx.exception))

    def test_empty_generation_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))

            with self.assertRaises(OperatorError) as ctx:
                _run_design(root, narrative, id="mydesign", generate_mock=_fake_generate_empty)

            self.assertIn("no content generated", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
