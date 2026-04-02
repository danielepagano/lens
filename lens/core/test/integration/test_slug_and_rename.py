"""Integration tests for --slug on session operators and ``lens rename``.

Tests are numbered to enforce alphabetical (sequential) execution order, matching
the pattern used in ``TestHappyPath``.  Each test depends on state left by the
previous one.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

from lens.core.commands.rename_node import rename_node
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.design import DesignOperator
from lens.core.operators.section import SectionOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

_T = TypeVar("_T")


def _run(coro: Coroutine[Any, Any, _T]) -> _T:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return asyncio.run(coro)


class TestSlugAndRename(unittest.TestCase):
    """Sequential tests for --slug and rename on narrative nodes.

    State accumulates across tests; methods are numbered to force alphabetical
    ordering to match intended sequence.
    """

    _server: FakeLLMServer
    _project_dir: Path
    _orig_cwd: Path
    _keep_dir: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        cls._server = FakeLLMServer()
        cls._server.start()
        cls._project_dir = Path(tempfile.mkdtemp(prefix="lens_slug_rename_"))
        cls._orig_cwd = Path.cwd()
        setup_test_project(cls._project_dir, cls._server.base_url, dataset="testing")
        os.chdir(cls._project_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        os.chdir(cls._orig_cwd)
        cls._server.stop()
        if cls._keep_dir:
            print(f"\n[itest] project preserved: {cls._project_dir}")
        else:
            shutil.rmtree(str(cls._project_dir), ignore_errors=True)

    def tearDown(self) -> None:
        result = getattr(getattr(self, "_outcome", None), "result", None)
        if result is not None:
            if getattr(result, "failures", []) or getattr(result, "errors", []):
                TestSlugAndRename._keep_dir = True

    def _session(self) -> ProjectSession:
        return ProjectSession(self._project_dir, self._project_dir)

    def _checkpoint(self, msg: str = "checkpoint") -> None:
        Storage(self._project_dir).checkpoint(msg)

    # ------------------------------------------------------------------
    # 01 — explicit --slug creates a named design sub-node
    # ------------------------------------------------------------------

    def test_01_slug_explicit_creates_named_node(self) -> None:
        """--slug 'my-tavern' on design creates 'design-my-tavern' (prefix auto-added)."""
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None

        _run(DesignOperator.run_design(
            session=session,
            narrative=narrative,
            prompt="design a tavern",
            module_id=None,
            pins=[],
            unpins=[],
            llm_id="mock",
            slug="my-tavern",
        ))

        cursor = narrative.find_cursor()
        # The operator prefix "design-" is auto-prepended.
        self.assertEqual(cursor.key_path[-1], "design-my-tavern")
        parent = NarrativeNode(
            narrative_root=narrative.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        self.assertIn("[design:design-my-tavern]: #", parent.md_path().read_text())
        self._checkpoint("slug: design my-tavern")

    # ------------------------------------------------------------------
    # 02 — --slug conflict raises OperatorError
    # ------------------------------------------------------------------

    def test_02_slug_conflict_raises(self) -> None:
        """--slug with a name that already exists raises OperatorError."""
        # cursor is inside my-tavern; close it first so we can try creating again
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        _run(DesignOperator.run_session_end(session=session, narrative=narrative, llm_id="mock"))
        self._checkpoint("design: close my-tavern for conflict test")

        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        with self.assertRaises(OperatorError) as ctx:
            _run(DesignOperator.run_design(
                session=session,
                narrative=narrative,
                prompt="another tavern",
                module_id=None,
                pins=[],
                unpins=[],
                llm_id="mock",
                slug="my-tavern",  # resolves to design-my-tavern which already exists
            ))
        self.assertIn("already exists", str(ctx.exception))

    # ------------------------------------------------------------------
    # 03 — --slug with invalid characters raises OperatorError
    # ------------------------------------------------------------------

    def test_03_slug_invalid_raises(self) -> None:
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        with self.assertRaises(OperatorError) as ctx:
            _run(DesignOperator.run_design(
                session=session,
                narrative=narrative,
                prompt="bad slug",
                module_id=None,
                pins=[],
                unpins=[],
                llm_id="mock",
                slug="invalid slug!",
            ))
        self.assertIn("invalid slug", str(ctx.exception))

    # ------------------------------------------------------------------
    # 04 — --slug is rejected when already inside a session
    # ------------------------------------------------------------------

    def test_04_slug_on_existing_session_raises(self) -> None:
        """--slug is rejected when the cursor is already inside a session."""
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None

        # Start a session without slug first
        _run(DesignOperator.run_design(
            session=session,
            narrative=narrative,
            prompt="start a design",
            module_id=None,
            pins=[],
            unpins=[],
            llm_id="mock",
        ))
        self._checkpoint("slug: design auto (for slug-on-existing test)")

        # Now try to provide --slug while inside the session
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        with self.assertRaises(OperatorError) as ctx:
            _run(DesignOperator.run_design(
                session=session,
                narrative=narrative,
                prompt="continue",
                module_id=None,
                pins=[],
                unpins=[],
                llm_id="mock",
                slug="other-name",
            ))
        self.assertIn("new session", str(ctx.exception))

        # Close the session so state is clean for next tests
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        _run(DesignOperator.run_session_end(session=session, narrative=narrative, llm_id="mock"))
        self._checkpoint("design: close auto session")

    # ------------------------------------------------------------------
    # 05 — rename a leaf section node
    # ------------------------------------------------------------------

    def test_05_rename_leaf_node(self) -> None:
        """Renaming a leaf (section) node updates annotation and file.

        Section nodes have no operator prefix, so the new slug is used as-is.
        """
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None

        cursor = narrative.find_cursor()
        cursor_md = cursor.md_path()
        rel = str(cursor_md.relative_to(session.git_root))
        storage = session.new_storage(owner=SectionOperator.owner_id("old-section", rel))
        SectionOperator(storage, narrative).start("old-section")
        self._checkpoint("section: start old-section")

        # Rename it
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        self.assertEqual(cursor.key_path[-1], "old-section")

        storage = session.new_storage()
        effective = rename_node(cursor, "new-section", storage)

        # section nodes have no operator prefix → new slug used as-is
        self.assertEqual(effective, "new-section")

        parent = NarrativeNode(
            narrative_root=narrative.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        parent_text = parent.md_path().read_text()
        self.assertIn("[section:new-section]: #", parent_text)
        self.assertNotIn("[section:old-section]: #", parent_text)

        old_file = self._project_dir / "narrative" / "story" / "old-section.md"
        new_file = self._project_dir / "narrative" / "story" / "new-section.md"
        self.assertFalse(old_file.exists(), "old file should be gone")
        self.assertTrue(new_file.exists(), "new file should exist")
        self._checkpoint("rename: old-section → new-section")

    # ------------------------------------------------------------------
    # 06 — cursor follows the renamed node
    # ------------------------------------------------------------------

    def test_06_rename_cursor_follows(self) -> None:
        """After rename, find_cursor() resolves to the new slug."""
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        self.assertEqual(cursor.key_path[-1], "new-section")

    # ------------------------------------------------------------------
    # 07 — rename conflict raises ValueError
    # ------------------------------------------------------------------

    def test_07_rename_conflict_raises(self) -> None:
        """Renaming to an existing sibling slug raises ValueError."""
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        # cursor is inside new-section; try renaming it to my-tavern (already exists as-is,
        # section has no prefix so "my-tavern" is used directly → conflicts with design-my-tavern? No.
        # Let's use new-section itself which would be a no-op; instead conflict on new-section.
        # Actually just test with a slug that resolves to an existing sibling (design-my-tavern).
        # section has no prefix, so provide the exact name "design-my-tavern".
        storage = session.new_storage()
        with self.assertRaises(ValueError) as ctx:
            rename_node(cursor, "design-my-tavern", storage)
        self.assertIn("already exists", str(ctx.exception))

    # ------------------------------------------------------------------
    # 08 — rename root raises ValueError
    # ------------------------------------------------------------------

    def test_08_rename_root_raises(self) -> None:
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        root = NarrativeNode(narrative_root=narrative.narrative_root, key_path=())
        storage = session.new_storage()
        with self.assertRaises(ValueError) as ctx:
            rename_node(root, "anything", storage)
        self.assertIn("root", str(ctx.exception))

    # ------------------------------------------------------------------
    # 09 — rename with invalid new slug raises ValueError
    # ------------------------------------------------------------------

    def test_09_rename_invalid_slug_raises(self) -> None:
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()  # inside new-section
        storage = session.new_storage()
        with self.assertRaises(ValueError) as ctx:
            rename_node(cursor, "bad name!", storage)
        self.assertIn("invalid slug", str(ctx.exception))

    # ------------------------------------------------------------------
    # 10 — rename a folder node (design sub-node)
    # ------------------------------------------------------------------

    def test_10_rename_folder_node(self) -> None:
        """Renaming a folder node (design sub-node) renames the directory."""
        # Close the current section so cursor is back at root
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        key = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=narrative.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        rel_parent = str(parent.md_path().relative_to(session.git_root))
        storage = session.new_storage(owner=SectionOperator.owner_id(key, rel_parent))
        _run(SectionOperator(storage, narrative).end(session, llm_id="mock"))
        self._checkpoint("section: close new-section")

        # Start a design session with --slug "old-dungeon" → actual id: "design-old-dungeon"
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        _run(DesignOperator.run_design(
            session=session,
            narrative=narrative,
            prompt="design a dungeon",
            module_id=None,
            pins=[],
            unpins=[],
            llm_id="mock",
            slug="old-dungeon",
        ))
        self._checkpoint("slug: design old-dungeon")

        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        # "design-" prefix auto-added, so actual id is design-old-dungeon
        self.assertEqual(cursor.key_path[-1], "design-old-dungeon")

        storage = session.new_storage()
        # rename "dungeon" → auto-prefixed to "design-new-dungeon"
        effective = rename_node(cursor, "new-dungeon", storage)
        self.assertEqual(effective, "design-new-dungeon")

        # The node is a leaf .md file (design sub-nodes are leaves until they get children)
        old_file = self._project_dir / "narrative" / "story" / "design-old-dungeon.md"
        new_file = self._project_dir / "narrative" / "story" / "design-new-dungeon.md"
        self.assertFalse(old_file.exists(), "old file should be gone")
        self.assertTrue(new_file.exists(), "new file should exist")

        parent = NarrativeNode(
            narrative_root=narrative.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        parent_text = parent.md_path().read_text()
        self.assertIn("[design:design-new-dungeon]: #", parent_text)
        self.assertNotIn("[design:design-old-dungeon]: #", parent_text)
        self._checkpoint("rename: design-old-dungeon → design-new-dungeon")

    # ------------------------------------------------------------------
    # 11 — rename a closed session (has both open and close tags)
    # ------------------------------------------------------------------

    def test_11_rename_with_close_tag(self) -> None:
        """Renaming a closed session updates both open and close tags."""
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None

        # Close the design session so we get a close tag
        _run(DesignOperator.run_session_end(session=session, narrative=narrative, llm_id="mock"))
        self._checkpoint("design: close new-dungeon")

        # cursor is back at parent; rename the closed new-dungeon node
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()

        # After test_10, the node is "design-new-dungeon"
        dungeon_node = NarrativeNode(
            narrative_root=narrative.narrative_root,
            key_path=cursor.key_path + ("design-new-dungeon",),
        )
        self.assertTrue(dungeon_node.exists())

        # Verify the close tag is there before rename
        parent_text = cursor.md_path().read_text()
        self.assertIn("[/design:design-new-dungeon]: #", parent_text)

        storage = session.new_storage()
        # rename: "renamed-dungeon" → auto-prefixed to "design-renamed-dungeon"
        effective = rename_node(dungeon_node, "renamed-dungeon", storage)
        self.assertEqual(effective, "design-renamed-dungeon")

        parent_text = cursor.md_path().read_text()
        self.assertIn("[design:design-renamed-dungeon]: #", parent_text)
        self.assertIn("[/design:design-renamed-dungeon]: #", parent_text)
        self.assertNotIn(":design-new-dungeon]: #", parent_text)
        self._checkpoint("rename: design-new-dungeon → design-renamed-dungeon (with close tag)")
