"""Tests for --slug nesting a fresh play session inside an active one."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
from lens.core.test.llm_run_mock import mock_run_llm
from lens.rpg.operators.play import PlayOperator


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


def _make_play_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    project = (
        f'[project]\nnarrative = "{slug}"\ndatasets = {json.dumps(["rpg"])}\n'
        '[[llm]]\nbase_url = "https://api.example.com/v1"\nmodel = "test"\n'
    )
    (tmp / "lens.toml").write_text(project)
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(
        "[\n  kb_pin:\n    - pc.bob\n]: #\n\n# test\n"
    )
    (tmp / "knowledge").mkdir(exist_ok=True)
    pc_dir = tmp / "knowledge" / "pc"
    pc_dir.mkdir(parents=True)
    (pc_dir / "bob.md").write_text("Bob the PC\n")
    npc_dir = tmp / "knowledge" / "npc"
    npc_dir.mkdir(parents=True)
    (npc_dir / "goblin.md").write_text("A goblin ambusher\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    node = NarrativeNode(narrative_root=narrative_dir, key_path=())
    return tmp, node


async def _never_generate_text(*_args: Any, **_kwargs: Any) -> str:
    raise AssertionError("LLM generation must not be called unless --pass is used")


async def _mock_summary(*_args: Any, **_kwargs: Any) -> str:
    return "The ambush is repelled."


class TestPlayNesting(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        self.root, self.narrative = _make_play_project(tmp)
        self.session = ProjectSession(git_root=self.root, project_root=self.root)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()
        self._tmp.cleanup()

    def _run(self, coro: Any) -> Any:
        with patch("lens.core.operator.run_llm", mock_run_llm(_never_generate_text)):
            return asyncio.run(coro)

    def test_slug_while_inside_play_session_nests_child_session(self) -> None:
        # Start the outer session: "the journey".
        self._run(
            PlayOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="we set out on the four-day journey",
                pins=[],
                unpins=[],
                extra_params=None,
            )
        )
        outer_node = self.narrative.find_cursor()
        self.assertEqual(outer_node.key_path[-1].split("-")[0], "play")

        # An ambush interrupts day two: nest a fresh play session here, with a
        # KB pin scoped to just the ambush (not the outer journey node).
        self._run(
            PlayOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="goblins spring from the treeline",
                pins=["npc.goblin"],
                unpins=[],
                slug="ambush",
                extra_params=None,
            )
        )

        nested_node = self.narrative.find_cursor()
        self.assertEqual(nested_node.key_path[:-1], outer_node.key_path)
        self.assertEqual(nested_node.key_path[-1], "play-ambush")

        outer_text = outer_node.md_path().read_text(encoding="utf-8")
        self.assertIn("[play:play-ambush]: #", outer_text)
        self.assertNotIn("npc.goblin", outer_text)

        nested_text = nested_node.md_path().read_text(encoding="utf-8")
        self.assertIn("npc.goblin", nested_text)

        # Ending the nested session pops the cursor back to the still-open
        # outer session, not to the root. The close summary is a separate
        # LLM call (session.py's own run_llm import), so mock it directly.
        with patch(
            "lens.core.operators.session.run_llm",
            mock_run_llm(_mock_summary),
        ):
            asyncio.run(
                PlayOperator.run_session_end(
                    session=self.session,
                    narrative=self.narrative,
                )
            )
        self.assertEqual(self.narrative.find_cursor().key_path, outer_node.key_path)

        # The outer session is still open and can keep going.
        self._run(
            PlayOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="the party presses on",
                pins=[],
                unpins=[],
                extra_params=None,
            )
        )
        self.assertEqual(
            self.narrative.find_cursor().key_path, outer_node.key_path
        )
