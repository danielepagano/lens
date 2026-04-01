"""Tests for play player-line append behavior (no LLM unless --pass)."""

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
from lens.core.narrative import NarrativeNode
from lens.core.project import ProjectSession
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


async def _mock_gm_reply(*_args: Any, **_kwargs: Any) -> str:
    return "The scene continues.\n"


class TestPlayAppend(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        self.root, self.narrative = _make_play_project(tmp)
        self.session = ProjectSession(git_root=self.root, project_root=self.root)
        KnowledgeStore.clear_registry()

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        self._tmp.cleanup()

    def _play_child_md(self) -> str:
        keys = [k for k in self.narrative.child_keys() if k.startswith("play-")]
        self.assertEqual(len(keys), 1, keys)
        child = self.narrative.child_node(keys[0])
        return child.md_path().read_text(encoding="utf-8")

    def test_appends_player_blockquote_without_llm(self) -> None:
        with patch("lens.core.operator.generate_text", _never_generate_text):
            asyncio.run(
                PlayOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="I ready my shield",
                    pins=[],
                    unpins=[],
                    extra_params=None,
                )
            )
        text = self._play_child_md()
        self.assertIn("> [Player] I ready my shield", text)
        self.assertNotIn("[play\n", text)
        self.assertNotIn("[/play", text)

    def test_mention_html_comment_strips_inner_html_comments(self) -> None:
        spell_dir = self.root / "knowledge" / "spell"
        spell_dir.mkdir(parents=True)
        (spell_dir / "foo.md").write_text(
            "Guidance cantrip\n\n<!-- inner-secret -->\nvisible line\n"
        )
        subprocess.run(
            ["git", "add", "-A"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "spell"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        KnowledgeStore.clear_registry()

        with patch("lens.core.operator.generate_text", _never_generate_text):
            asyncio.run(
                PlayOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="I cast @spell.foo",
                    pins=[],
                    unpins=[],
                    extra_params=None,
                )
            )
        text = self._play_child_md()
        self.assertIn("> [Player] I cast @spell.foo", text)
        self.assertIn("<!---", text)
        self.assertIn("KB['spell.foo']", text)
        self.assertIn("visible line", text)
        self.assertNotIn("inner-secret", text)
        self.assertEqual(text.count("-->"), 1)

    def test_mention_kb_is_not_emitted_twice(self) -> None:
        spell_dir = self.root / "knowledge" / "spell"
        spell_dir.mkdir(parents=True)
        (spell_dir / "foo.md").write_text("Foo spell\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "spell"], cwd=self.root, capture_output=True, check=True)
        KnowledgeStore.clear_registry()

        with patch("lens.core.operator.generate_text", _never_generate_text):
            asyncio.run(
                PlayOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="I cast @spell.foo",
                    pins=[],
                    unpins=[],
                    extra_params=None,
                )
            )
            asyncio.run(
                PlayOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="I cast @spell.foo again",
                    pins=[],
                    unpins=[],
                    extra_params=None,
                )
            )
        text = self._play_child_md()
        self.assertEqual(text.count("KB['spell.foo']"), 1)

    def test_pass_only_after_player_turn_with_prior_gm_block(self) -> None:
        """Regression: pending owner can match the last [play] tag in-file; --pass must still run."""
        with patch("lens.core.operator.generate_text", _mock_gm_reply):
            asyncio.run(
                PlayOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="I approach",
                    pins=[],
                    unpins=[],
                    extra_params={"pass": True},
                )
            )
        with patch("lens.core.operator.generate_text", _never_generate_text):
            asyncio.run(
                PlayOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="I wait",
                    pins=[],
                    unpins=[],
                    extra_params=None,
                )
            )
        with patch("lens.core.operator.generate_text", _mock_gm_reply):
            asyncio.run(
                PlayOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    pins=[],
                    unpins=[],
                    extra_params={"pass": True},
                )
            )
        text = self._play_child_md()
        self.assertIn("> [Player] I approach", text)
        self.assertIn("> [Player] I wait", text)
        self.assertGreaterEqual(text.count("[/play"), 2)
