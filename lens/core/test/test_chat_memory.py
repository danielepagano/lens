"""Tests for chat inline tools behavior and kb_patch whitelist bundle."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.command_tools import CommandToolFn
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operators.chat import ChatOperator
from lens.core.project import ProjectSession


def _init_repo(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )


def _make_chat_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    project = (
        f'[project]\nnarrative = "{slug}"\n'
        '[[llm]]\nbase_url = "https://api.example.com/v1"\nmodel = "test"\n'
    )
    (tmp / "lens.toml").write_text(project)
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")

    kb_root = tmp / "knowledge"
    kb_root.mkdir(exist_ok=True)
    npc_dir = kb_root / "npc"
    npc_dir.mkdir()
    (npc_dir / "bob.md").write_text("Bob is a gruff innkeeper.\n")
    (npc_dir / "waiter.md").write_text("The waiter hovers nearby.\n")
    pc_dir = kb_root / "pc"
    pc_dir.mkdir()
    (pc_dir / "amy.md").write_text("Amy is a bard.\n")

    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    node = NarrativeNode(narrative_root=narrative_dir, key_path=())
    return tmp, node


class TestChatMemory(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        self.root, self.narrative = _make_chat_project(tmp)
        self.session = ProjectSession(git_root=self.root, project_root=self.root)
        KnowledgeStore.clear_registry()

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        self._tmp.cleanup()

    def test_oneshot_no_memory_no_tools(self) -> None:
        captured: dict[str, Any] = {}

        async def _capture_gen(
            _messages: list[dict[str, Any]], _pr: Path, **kwargs: Any
        ) -> str:
            captured.update(kwargs)
            return "> [Bob] Hi.\n"

        with patch("lens.core.operator.generate_text", _capture_gen):
            asyncio.run(
                ChatOperator.run_inline(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    pins=[],
                    unpins=[],
                    llm_id=None,
                    reasoning=None,
                    retry=False,
                    on_token=None,
                    cancel_event=None,
                    extra_params={"as_kb_id": "npc.bob"},
                )
            )
        self.assertIsNone(captured.get("tools"))
        self.assertIsNone(captured.get("command_tool_handlers"))


class TestKbPatchWhitelistBundle(unittest.TestCase):
    def test_guard_rejects_non_whitelisted_id(self) -> None:
        from lens.core.llm import build_kb_patch_whitelist_bundle

        bundle = build_kb_patch_whitelist_bundle(frozenset({"npc.bob"}))
        handlers = bundle.handlers
        self.assertIsNotNone(handlers)
        assert handlers is not None
        kb_patch: CommandToolFn = handlers["kb_patch"]

        async def _run() -> str:
            result = await kb_patch(
                {
                    "id": "npc.waiter",
                    "patches": [{"start": {"target": "x"}, "content": "y"}],
                },
                Path("/tmp"),
            )
            assert isinstance(result, str)
            return result

        out = asyncio.run(_run())
        self.assertIn("error", out.lower())
        self.assertIn("npc.bob", out)
