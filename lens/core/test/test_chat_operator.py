"""Tests for ChatOperator."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.chat import ChatOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage


def _init_repo(tmp: Path) -> None:
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


def _make_chat_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    """Create a minimal Lens project with npc.bob and pc.amy KB objects."""
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
    (npc_dir / "bob.md").write_text("Bob is a gruff innkeeper with a soft spot for travellers.\n")
    pc_dir = kb_root / "pc"
    pc_dir.mkdir()
    (pc_dir / "amy.md").write_text("Amy is a wandering bard.\n")

    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True,
    )
    node = NarrativeNode(narrative_root=narrative_dir, key_path=())
    return tmp, node


async def _mock_generate(*_args: Any, **_kwargs: Any) -> str:
    return "> [Bob] Aye, what can I get for ye?\n"


# ---------------------------------------------------------------------------
# One-shot inline mode (no --with)
# ---------------------------------------------------------------------------

class TestChatOneShot(unittest.TestCase):
    """Tests for one-shot inline mode: no --with, AI responds in current node."""

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

    def _narrative_md(self) -> str:
        return self.narrative.md_path().read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # One-shot: response written inline, no sub-node created
    # ------------------------------------------------------------------

    def test_oneshot_response_written_inline(self) -> None:
        """One-shot writes AI response to the current narrative node."""
        with patch("lens.core.operator.generate_text", _mock_generate):
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
        text = self._narrative_md()
        self.assertIn("[Bob] Aye, what can I get for ye?", text)
        self.assertIn("[chat\n", text)
        self.assertIn("[/chat]: #", text)

    def test_oneshot_no_subnode_created(self) -> None:
        """One-shot does not create a chat sub-node."""
        with patch("lens.core.operator.generate_text", _mock_generate):
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
        chat_children = [k for k in self.narrative.child_keys() if k.startswith("chat")]
        self.assertEqual(chat_children, [], "one-shot must not create a sub-node")

    def test_oneshot_stores_as_kb_id_in_annotation(self) -> None:
        """One-shot stores as_kb_id in the inline annotation params."""
        with patch("lens.core.operator.generate_text", _mock_generate):
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
        text = self._narrative_md()
        self.assertIn("as_kb_id: npc.bob", text)

    def test_oneshot_stage_directions_in_annotation(self) -> None:
        """Stage directions are stored in the inline annotation params."""
        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_inline(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="The inn is quiet at dawn.",
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
        text = self._narrative_md()
        self.assertIn("The inn is quiet at dawn.", text)

    def test_oneshot_requires_as_kb_id(self) -> None:
        """One-shot raises OperatorError when --as is not provided."""
        with self.assertRaises(OperatorError):
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
                    extra_params={},
                )
            )


# ---------------------------------------------------------------------------
# Session mode (with --with)
# ---------------------------------------------------------------------------

class TestChatSession(unittest.TestCase):
    """Tests for session mode: --with triggers sub-node creation."""

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

    def _chat_child_md(self) -> str:
        keys = [k for k in self.narrative.child_keys() if k.startswith("chat")]
        self.assertEqual(len(keys), 1, f"expected one chat child, got: {keys}")
        child = self.narrative.child_node(keys[0])
        return child.md_path().read_text(encoding="utf-8")

    def _chat_child_node(self) -> NarrativeNode:
        keys = [k for k in self.narrative.child_keys() if k.startswith("chat")]
        self.assertEqual(len(keys), 1, f"expected one chat child, got: {keys}")
        return self.narrative.child_node(keys[0])

    # ------------------------------------------------------------------
    # Fresh session creation (requires --with)
    # ------------------------------------------------------------------

    def test_session_slug_includes_character_keys(self) -> None:
        """Session ID includes the --as and --with character keys."""
        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="at the inn",
                    module_id=None,
                    pins=["pc.amy"],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        keys = [k for k in self.narrative.child_keys() if k.startswith("chat")]
        self.assertEqual(len(keys), 1)
        self.assertIn("bob", keys[0])
        self.assertIn("amy", keys[0])

    def test_session_creates_subnode(self) -> None:
        """Starting a session with --with creates a chat sub-node."""
        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=["pc.amy"],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        keys = [k for k in self.narrative.child_keys() if k.startswith("chat")]
        self.assertEqual(len(keys), 1)

    def test_session_pins_counterpart_in_front_matter(self) -> None:
        """The --with counterpart is pinned in the sub-node for scene context.
        The --as character is NOT pinned (content goes into the task directly)."""
        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=["pc.amy"],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        self.assertIn("pc.amy", text)
        self.assertNotIn("kb_pin:\n- npc.bob", text)

    def test_session_ai_response_written(self) -> None:
        """The AI response is written into the chat sub-node."""
        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=["pc.amy"],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        self.assertIn("[Bob] Aye, what can I get for ye?", text)
        self.assertIn("[chat\n", text)
        self.assertIn("[/chat]: #", text)

    def test_session_stores_character_ids_in_annotation(self) -> None:
        """as_kb_id and with_kb_id are stored in the sub-node annotation."""
        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=["pc.amy"],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        self.assertIn("as_kb_id: npc.bob", text)
        self.assertIn("with_kb_id: pc.amy", text)

    def test_session_with_stage_directions(self) -> None:
        """Stage directions in the prompt are stored and included in context."""
        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="The inn is quiet at dawn.",
                    module_id=None,
                    pins=["pc.amy"],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        self.assertIn("The inn is quiet at dawn.", text)

    def test_session_requires_as(self) -> None:
        """Starting a session without --as raises OperatorError."""
        with self.assertRaises(OperatorError):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=["pc.amy"],
                    unpins=[],
                    extra_params={"with_kb_id": "pc.amy"},
                )
            )

    # ------------------------------------------------------------------
    # Session continuation
    # ------------------------------------------------------------------

    def _start_session(self) -> None:
        """Helper: start a fresh session with npc.bob (as) and pc.amy (with)."""
        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=["pc.amy"],  # only counterpart is pinned; --as goes into task
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        # stage after first turn so continuation can proceed
        Storage(self.root).stage_all()

    def test_session_continuation_appends_with_line(self) -> None:
        """Sending a message inside a session appends it as the --with character."""
        self._start_session()
        KnowledgeStore.clear_registry()

        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="A pint of your best, please.",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        self.assertIn("> [Amy] A pint of your best, please.", text)

    def test_session_continuation_triggers_ai_response(self) -> None:
        """After appending the user line, the AI generates a new response."""
        self._start_session()
        KnowledgeStore.clear_registry()

        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="A pint of your best, please.",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        # Should have two AI response blocks
        self.assertGreaterEqual(text.count("[chat\n"), 2)
        self.assertGreaterEqual(text.count("[/chat]: #"), 2)

    def test_session_continuation_derives_as_from_annotation(self) -> None:
        """Omitting --as in continuation falls back to the last annotation's value."""
        self._start_session()
        KnowledgeStore.clear_registry()

        with patch("lens.core.operator.generate_text", _mock_generate):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="Quiet today.",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={},  # no --as specified
                )
            )
        text = self._chat_child_md()
        # Must still produce a response (derived npc.bob from annotation)
        self.assertGreaterEqual(text.count("[/chat]: #"), 2)

    def test_annotation_stores_character_ids(self) -> None:
        """as_kb_id and with_kb_id survive the annotation roundtrip."""
        self._start_session()
        text = self._chat_child_md()
        self.assertIn("as_kb_id: npc.bob", text)
        self.assertIn("with_kb_id: pc.amy", text)

    # ------------------------------------------------------------------
    # Session end
    # ------------------------------------------------------------------

    def test_session_end_closes_subnode(self) -> None:
        """--end appends a close tag to the parent node."""
        self._start_session()
        KnowledgeStore.clear_registry()

        async def _mock_summary(*_args: Any, **_kwargs: Any) -> str:
            return "A brief exchange at the inn."

        # run_session_end calls generate_text from lens.core.operators.session
        with patch("lens.core.operators.session.generate_text", _mock_summary):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    end=True,
                    extra_params={},
                )
            )
        root_text = self.narrative.md_path().read_text(encoding="utf-8")
        self.assertIn("[/chat:", root_text)
