"""Tests for ChatOperator."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.exceptions import ValidationError
from lens.core.operator import OperatorError
from lens.core.operators.chat import ChatOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.core.test.llm_run_mock import mock_run_llm


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
    (npc_dir / "waiter.md").write_text("The waiter is nervous but attentive, always hovering nearby.\n")
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


def _text_after_first_chat_close(text: str) -> str:
    marker = "[/chat]: #"
    idx = text.find(marker)
    if idx == -1:
        raise AssertionError("expected at least one [/chat]: # in transcript")
    return text[idx + len(marker) :]


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

    def test_oneshot_response_written_inline(self) -> None:
        """One-shot writes AI response to the current narrative node."""
        with patch(
            "lens.core.operator.run_llm",
            mock_run_llm(_mock_generate),
        ):
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
        self.assertIn("[chat", text)
        self.assertIn("[/chat]: #", text)

    def test_oneshot_no_subnode_created(self) -> None:
        """One-shot does not create a chat sub-node."""
        with patch(
            "lens.core.operator.run_llm",
            mock_run_llm(_mock_generate),
        ):
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
        with patch(
            "lens.core.operator.run_llm",
            mock_run_llm(_mock_generate),
        ):
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
        with patch(
            "lens.core.operator.run_llm",
            mock_run_llm(_mock_generate),
        ):
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
        header_end = text.find("]: #")
        self.assertNotEqual(header_end, -1)
        after_ann = text[header_end + len("]: #") :]
        self.assertIn("**Scene:** The inn is quiet at dawn.", after_ann)
        self.assertLess(
            after_ann.find("**Scene:**"),
            after_ann.find("[Bob]"),
        )

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
# One-shot inside another operator's sub-node (e.g. play node)
# ---------------------------------------------------------------------------

class TestChatOneShotInPlayContext(unittest.TestCase):
    """One-shot chat when the cursor lives inside a different operator's sub-node."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        _init_repo(tmp)
        self.root, self.narrative = _make_chat_project(tmp)
        self.session = ProjectSession(git_root=self.root, project_root=self.root)
        KnowledgeStore.clear_registry()

        # Simulate a play sub-node: create a child node and write an unclosed
        # play annotation in the parent so the cursor points to the child.
        self._play_child = self._create_play_child()

    def tearDown(self) -> None:
        KnowledgeStore.clear_registry()
        self._tmp.cleanup()

    def _create_play_child(self) -> NarrativeNode:
        """Create a sub-node with an unclosed [play:play-abc] annotation in parent."""
        narrative_dir = self.narrative.narrative_root
        # Promote root to folder node if not already
        root_md = self.narrative.md_path()
        if root_md.parent == narrative_dir:
            # Already a folder-node (narrative/_node.md)
            pass

        # Create child directory structure
        child_dir = narrative_dir / "play-abc"
        child_dir.mkdir(exist_ok=True)
        child_md = child_dir / "_node.md"
        child_md.write_text("The adventurers enter the dungeon.\n")

        # Promote root node to folder if needed (root _node.md already exists)
        parent_text = root_md.read_text(encoding="utf-8")
        root_md.write_text(parent_text + "\n[play:play-abc]: #\n")

        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "play-session"],
            cwd=self.root, capture_output=True, check=True,
        )

        child_node = NarrativeNode(
            narrative_root=narrative_dir,
            key_path=("play-abc",),
        )
        return child_node

    def test_oneshot_in_play_node_writes_inline(self) -> None:
        """One-shot chat inside a play sub-node writes inline to that node."""
        with patch(
            "lens.core.operator.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_inline(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="describe how you feel",
                    pins=[],
                    unpins=[],
                    llm_id=None,
                    reasoning=None,
                    retry=False,
                    on_token=None,
                    cancel_event=None,
                    extra_params={"as_kb_id": "npc.bob"},
                    _cursor_override=self._play_child,
                )
            )
        child_text = self._play_child.md_path().read_text(encoding="utf-8")
        self.assertIn("[Bob] Aye, what can I get for ye?", child_text)
        self.assertIn("[chat", child_text)
        self.assertIn("[/chat]: #", child_text)

    def test_oneshot_in_play_node_no_chat_subnode(self) -> None:
        """One-shot in a play node must not create a chat sub-node."""
        with patch(
            "lens.core.operator.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_inline(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="describe how you feel",
                    pins=[],
                    unpins=[],
                    llm_id=None,
                    reasoning=None,
                    retry=False,
                    on_token=None,
                    cancel_event=None,
                    extra_params={"as_kb_id": "npc.bob"},
                    _cursor_override=self._play_child,
                )
            )
        # No chat child should have been created under the play sub-node
        chat_children = [k for k in self._play_child.child_keys() if k.startswith("chat")]
        self.assertEqual(chat_children, [])

    def test_find_active_session_returns_none_in_play_node(self) -> None:
        """find_active_session sees a play annotation, not chat — returns None."""
        session_node, session_id = ChatOperator.find_active_session(self.narrative)
        self.assertIsNone(session_node)
        self.assertIsNone(session_id)


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

    def _narrative_md(self) -> str:
        return self.narrative.md_path().read_text(encoding="utf-8")

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
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="at the inn",
                    module_id=None,
                    pins=[],
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
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        keys = [k for k in self.narrative.child_keys() if k.startswith("chat")]
        self.assertEqual(len(keys), 1)

    def test_session_does_not_kb_pin_with_counterpart(self) -> None:
        """--with is crawl context only; counterpart is not duplicated in kb_pin."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        self.assertNotIn("kb_pin:\n- pc.amy", text)
        self.assertNotIn("kb_pin:\n- npc.bob", text)

    def test_session_explicit_pins_still_in_child_front_matter(self) -> None:
        """User --pin ids are still written to the session sub-node front matter."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
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

    def test_session_ai_response_written(self) -> None:
        """The AI response is written into the chat sub-node."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        self.assertIn("[Bob] Aye, what can I get for ye?", text)
        self.assertIn("[/chat]: #", text)

    def test_session_params_in_parent_annotation(self) -> None:
        """as_kb_id and with_kb_id are stored in the PARENT node's session annotation."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        parent_text = self._narrative_md()
        self.assertIn("as_kb_id: npc.bob", parent_text)
        self.assertIn("with_kb_id: pc.amy", parent_text)

    def test_session_with_stage_directions_in_parent(self) -> None:
        """Stage directions given at session start appear in the parent annotation."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="The inn is quiet at dawn.",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        parent_text = self._narrative_md()
        self.assertIn("The inn is quiet at dawn.", parent_text)

    def test_session_opening_scene_persisted_in_child(self) -> None:
        """Opening scene is written at the start of the first [chat] block in the child."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="The inn is quiet at dawn.",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        open_tag = "[chat]: #"
        idx_open = text.find(open_tag)
        self.assertNotEqual(idx_open, -1)
        inner = text[idx_open + len(open_tag) :]
        idx_close = inner.find("[/chat]: #")
        self.assertNotEqual(idx_close, -1)
        first_turn = inner[:idx_close]
        self.assertIn("**Scene:** The inn is quiet at dawn.", first_turn)
        self.assertLess(
            first_turn.find("**Scene:**"),
            first_turn.find("[Bob]"),
        )

    def test_session_opening_scene_multiline_in_child(self) -> None:
        """Multiline opening scene uses a block after **Scene:** in the child."""
        scene = "Line one.\nLine two."
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=scene,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        text = self._chat_child_md()
        self.assertIn("**Scene:**\n\nLine one.\nLine two.", text)
        self.assertLess(text.find("Line two."), text.find("[Bob]"))

    def test_session_requires_as(self) -> None:
        """Starting a session without --as raises ValidationError."""
        with self.assertRaises(ValidationError):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"with_kb_id": "pc.amy"},
                )
            )

    def test_session_is_one_atomic_transaction(self) -> None:
        """Fresh session: sub-node creation + first AI turn are in one unstaged transaction."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        # Everything should be unstaged (pending) — no intermediate stage_all.
        storage = Storage(self.root)
        self.assertTrue(storage.has_pending(), "fresh session must leave an unstaged transaction")
        self.assertFalse(storage.has_staged(), "nothing should be in the staging area yet")

    def test_session_rollback_removes_subnode(self) -> None:
        """Rolling back after a fresh session removes the sub-node entirely."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        Storage(self.root).rollback()
        keys = [k for k in self.narrative.child_keys() if k.startswith("chat")]
        self.assertEqual(keys, [], "rollback must remove the chat sub-node entirely")

    def test_session_recycles_empty_slug_file(self) -> None:
        """An empty leftover chat-*.md does not block reusing that slug."""
        (self.narrative.md_path().parent / "chat-monday.md").write_text("")
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="it's monday",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    slug="monday",
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        self.assertEqual(
            [k for k in self.narrative.child_keys() if k.startswith("chat")],
            ["chat-monday"],
        )
        self.assertIn("[Bob]", self._chat_child_md())

    def test_retry_first_turn_rolls_back_and_regenerates(self) -> None:
        """--retry on an unstaged fresh session rolls back and re-runs the first turn."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        # All still unstaged — retry must not raise and must produce fresh content.
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    retry=True,
                    extra_params={},
                )
            )
        keys = [k for k in self.narrative.child_keys() if k.startswith("chat")]
        self.assertEqual(len(keys), 1, "retry must produce exactly one chat sub-node")
        child = self.narrative.child_node(keys[0])
        text = child.md_path().read_text(encoding="utf-8")
        self.assertIn("[Bob] Aye, what can I get for ye?", text)

    # ------------------------------------------------------------------
    # Session continuation
    # ------------------------------------------------------------------

    def _start_session(self) -> None:
        """Helper: start a fresh session with npc.bob (as) and pc.amy (with)."""
        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        # Stage after first turn so continuation sees a clean working tree.
        Storage(self.root).stage_all()

    def test_session_continuation_appends_with_line(self) -> None:
        """Sending a message inside a session appends it as the --with character."""
        self._start_session()
        KnowledgeStore.clear_registry()

        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
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

    def test_session_narrate_wait_plain_blockquote(self) -> None:
        """--narrate --wait appends one blockquote run (no [Name]) and no new [chat] pair."""
        self._start_session()
        KnowledgeStore.clear_registry()

        asyncio.run(
            ChatOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="Amy grips her sword.",
                module_id=None,
                pins=[],
                unpins=[],
                extra_params={
                    "as_kb_id": "npc.bob",
                    "with_kb_id": "pc.amy",
                    "narrate": True,
                    "wait": True,
                },
            )
        )
        text = self._chat_child_md()
        self.assertEqual(text.count("[/chat]: #"), 1)
        self.assertNotIn("narrate:", text)
        self.assertEqual(
            _text_after_first_chat_close(text),
            "\n\n> Amy grips her sword.\n",
        )

    def test_session_two_waits_blockquote_continuation(self) -> None:
        """Two --wait turns: bare ``>`` line between user quote lines (whole tail)."""
        self._start_session()
        KnowledgeStore.clear_registry()

        asyncio.run(
            ChatOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="She steadies her breath.",
                module_id=None,
                pins=[],
                unpins=[],
                extra_params={
                    "as_kb_id": "npc.bob",
                    "with_kb_id": "pc.amy",
                    "narrate": True,
                    "wait": True,
                },
            )
        )
        asyncio.run(
            ChatOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="What now?",
                module_id=None,
                pins=[],
                unpins=[],
                extra_params={
                    "as_kb_id": "npc.bob",
                    "with_kb_id": "pc.amy",
                    "wait": True,
                },
            )
        )
        text = self._chat_child_md()
        self.assertEqual(text.count("[/chat]: #"), 1)
        self.assertNotIn("narrate:", text)
        self.assertEqual(
            _text_after_first_chat_close(text),
            "\n\n> She steadies her breath.\n>\n> [Amy] What now?\n",
        )

    def test_session_three_waits_blockquote_spacers(self) -> None:
        """Dialogue / narrate / dialogue: full blockquote tail with ``>`` between each."""
        self._start_session()
        KnowledgeStore.clear_registry()

        asyncio.run(
            ChatOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="We can multi-task.",
                module_id=None,
                pins=[],
                unpins=[],
                extra_params={
                    "as_kb_id": "npc.bob",
                    "with_kb_id": "pc.amy",
                    "wait": True,
                },
            )
        )
        asyncio.run(
            ChatOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="I take a sip of coffee.",
                module_id=None,
                pins=[],
                unpins=[],
                extra_params={
                    "as_kb_id": "npc.bob",
                    "with_kb_id": "pc.amy",
                    "narrate": True,
                    "wait": True,
                },
            )
        )
        asyncio.run(
            ChatOperator.run_session(
                session=self.session,
                narrative=self.narrative,
                prompt="Delicious.",
                module_id=None,
                pins=[],
                unpins=[],
                extra_params={
                    "as_kb_id": "npc.bob",
                    "with_kb_id": "pc.amy",
                    "wait": True,
                },
            )
        )
        text = self._chat_child_md()
        self.assertEqual(text.count("[/chat]: #"), 1)
        self.assertEqual(
            _text_after_first_chat_close(text),
            "\n\n> [Amy] We can multi-task.\n"
            ">\n"
            "> I take a sip of coffee.\n"
            ">\n"
            "> [Amy] Delicious.\n",
        )

    def test_session_narrate_then_llm_full_tail(self) -> None:
        """--narrate without --wait: one plain blockquote user run then a full [chat] turn."""
        self._start_session()
        KnowledgeStore.clear_registry()

        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="The torch flickers.",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={
                        "as_kb_id": "npc.bob",
                        "with_kb_id": "pc.amy",
                        "narrate": True,
                    },
                )
            )
        text = self._chat_child_md()
        self.assertNotIn("narrate:", text)
        tail = _text_after_first_chat_close(text)
        self.assertIn("> The torch flickers.", tail)
        self.assertIn("as_kb_id: npc.bob", tail)
        self.assertIn("> [Bob] Aye, what can I get for ye?", tail)
        self.assertIn("[/chat]: #", tail)

    def test_session_continuation_triggers_ai_response(self) -> None:
        """After appending the user line, the AI generates a new response."""
        self._start_session()
        KnowledgeStore.clear_registry()

        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
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
        # Two complete AI turns → two close tags.
        self.assertGreaterEqual(text.count("[/chat]: #"), 2)

    def test_session_continuation_user_line_rolls_back_with_ai_turn(self) -> None:
        """Rollback drops the user's line and the new AI block in one transaction."""
        self._start_session()
        KnowledgeStore.clear_registry()

        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="A pint with a typo.",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        storage = Storage(self.root)
        self.assertTrue(storage.has_pending(), "continuation must leave one unstaged transaction")
        storage.rollback()
        text = self._chat_child_md()
        self.assertNotIn("A pint with a typo.", text)
        self.assertEqual(text.count("[/chat]: #"), 1)

    def test_session_continuation_retry_regenerates_last_turn(self) -> None:
        """--retry after a direct continuation re-runs the last AI block."""
        self._start_session()
        KnowledgeStore.clear_registry()

        seq = {"n": 0}

        async def _sequential(*_a: Any, **_kw: Any) -> str:
            seq["n"] += 1
            return f"> [Bob] turn-{seq['n']}\n"

        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_sequential),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="Order up.",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        mid = self._chat_child_md()
        self.assertIn("> [Amy] Order up.", mid)
        self.assertIn("turn-1", mid)

        with patch(
            "lens.core.operator.run_llm",
            mock_run_llm(_sequential),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=[],
                    unpins=[],
                    retry=True,
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        final = self._chat_child_md()
        self.assertIn("> [Amy] Order up.", final)
        self.assertIn("turn-2", final)
        self.assertNotIn("turn-1", final)

    def test_session_continuation_derives_params_from_parent(self) -> None:
        """Omitting --as in continuation derives it from the parent annotation."""
        self._start_session()
        KnowledgeStore.clear_registry()

        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
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
        # Must still produce a second AI turn (npc.bob derived from parent annotation).
        self.assertGreaterEqual(text.count("[/chat]: #"), 2)

    def test_session_butt_in_override(self) -> None:
        """Passing a different --as in continuation overrides the derived character."""
        self._start_session()
        KnowledgeStore.clear_registry()

        captured_messages: list[dict[str, str]] = []

        async def _waiter_generate(messages: list[dict[str, str]], *_args: Any, **_kwargs: Any) -> str:
            captured_messages.extend(messages)
            return "The waiter edges closer to the table, clutching a notepad.\n> [Waiter] Uh... can I take your order?\n"

        with patch(
            "lens.core.operator.run_llm",
            mock_run_llm(_waiter_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt="hesitantly interrupt them to take orders",
                    module_id=None,
                    pins=[],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.waiter"},
                )
            )
        text = self._chat_child_md()
        self.assertIn("[Waiter] Uh... can I take your order?", text)
        self.assertNotIn("> [Amy] hesitantly interrupt them to take orders", text)

        self.assertGreaterEqual(len(captured_messages), 2)
        # The task instruction is in the last user message (may not be messages[1]
        # with multi-turn assembly).
        last_user_content = next(
            m["content"] for m in reversed(captured_messages) if m["role"] == "user"
        )
        self.assertIn("one-off interruption inside an ongoing exchange", last_user_content)
        self.assertIn("neutral third-person scene guidance", last_user_content)
        self.assertNotIn('Write non-dialogue prose in first person ("I", "my", "me").', last_user_content)

    def test_derive_session_params_reads_parent_annotation(self) -> None:
        """_derive_session_params reads from the parent annotation, not child."""
        self._start_session()
        child_node = self._chat_child_node()
        derived = ChatOperator._derive_session_params(child_node)  # type: ignore[reportPrivateUsage]
        self.assertEqual(derived.get("as_kb_id"), "npc.bob")
        self.assertEqual(derived.get("with_kb_id"), "pc.amy")

    # ------------------------------------------------------------------
    # Session end
    # ------------------------------------------------------------------

    def test_session_end_closes_subnode(self) -> None:
        """--end appends a close tag to the parent node."""
        self._start_session()
        KnowledgeStore.clear_registry()

        async def _mock_summary(*_args: Any, **_kwargs: Any) -> str:
            return "A brief exchange at the inn."

        with patch(
            "lens.core.operators.session.run_llm",
            mock_run_llm(_mock_summary),
        ):
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

    def test_session_end_remember_crawl_includes_child_kb_pins(self) -> None:
        """Remember pass uses crawl at session child so kb_pin on child is visible."""
        lore_dir = self.root / "knowledge" / "lore"
        lore_dir.mkdir(exist_ok=True)
        (lore_dir / "alice.md").write_text("Alice.\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "lore"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        KnowledgeStore.clear_registry()
        store = KnowledgeStore.for_project(self.root)
        self.assertIsNone(store.add_tags("lore.alice", ["remember.note"]))

        with patch(
            "lens.core.operators.chat.run_llm",
            mock_run_llm(_mock_generate),
        ):
            asyncio.run(
                ChatOperator.run_session(
                    session=self.session,
                    narrative=self.narrative,
                    prompt=None,
                    module_id=None,
                    pins=["lore.alice"],
                    unpins=[],
                    extra_params={"as_kb_id": "npc.bob", "with_kb_id": "pc.amy"},
                )
            )
        Storage(self.root).stage_all()

        captured: dict[str, list[str]] = {}

        async def _remember_cap(*, crawl_result: Any, **kw: Any) -> str:
            captured["pinned_ids"] = list(crawl_result.pinned_ids)
            return ""

        async def _summary(*_a: Any, **_k: Any) -> str:
            return "The title\nSome body line."

        with patch(
            "lens.core.operators.session.run_llm",
            mock_run_llm(_summary),
        ):
            with patch(
                "lens.core.workflow_summarize.apply_remember_patches",
                AsyncMock(side_effect=_remember_cap),
            ):
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

        self.assertIn("lore.alice", captured["pinned_ids"])
        self.assertIn("npc.bob", captured["pinned_ids"])
        self.assertIn("pc.amy", captured["pinned_ids"])
