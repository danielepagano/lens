"""Integration tests: Python-API assertions on annotation format, git state,
operator semantics, and dataset behaviours.

These tests drive core operators through the *Python API* (not the CLI),
which lets them make precise assertions about annotation structure, git index
state, and dataset copy-on-write that CLI tests cannot easily replicate.

Infrastructure is shared from ``lens.testing``.  Use ``poe test-e2e`` for
full CLI / HTTP / browser coverage.

Run with::

    poe test-integration
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import patch

from lens.core.commands.kb import kb_edit
from lens.core.commands.rollback import execute_rollback
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operator import OperatorError
from lens.core.operators.collate import CollateOperator
from lens.core.operators.edit import EditOperator
from lens.core.operators.section import SectionOperator
from lens.core.operators.write import WriteOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.testing.fake_llm import (
    FAKE_SECRET_ROT13,
    FAKE_SECRET_TRIGGER,
    FakeLLMServer,
)
from lens.testing.project import setup_test_project


_T = TypeVar("_T")


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run a coroutine in the integration-test context (no running event loop)."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Happy-path suite
# ---------------------------------------------------------------------------


class TestHappyPath(unittest.TestCase):
    """Sequential happy-path regression across core Lens features.

    ``setUpClass`` uses ``setup_test_project`` which already performs git init,
    project init, KB population, pin, and a first write — so the suite starts
    with a committed project that has one ``[write …]`` passage.

    Methods are numbered to enforce execution order (unittest sorts
    alphabetically).  Each test depends on state left by the previous one.
    The temporary directory is preserved if any step fails.
    """

    _server: FakeLLMServer
    _project_dir: Path
    _orig_cwd: Path
    _keep_dir: bool = False
    _session: ProjectSession

    @classmethod
    def setUpClass(cls) -> None:
        cls._server = FakeLLMServer()
        cls._server.start()
        cls._project_dir = Path(tempfile.mkdtemp(prefix="lens_itest_"))
        cls._orig_cwd = Path.cwd()
        cls._session = setup_test_project(
            cls._project_dir, cls._server.base_url, dataset="testing"
        )
        os.chdir(cls._project_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        os.chdir(cls._orig_cwd)
        cls._server.stop()
        if cls._keep_dir:
            print(f"\n[itest] project preserved for inspection: {cls._project_dir}")
        else:
            shutil.rmtree(str(cls._project_dir), ignore_errors=True)

    def tearDown(self) -> None:
        result = getattr(getattr(self, "_outcome", None), "result", None)
        if result is not None:
            if getattr(result, "failures", []) or getattr(result, "errors", []):
                TestHappyPath._keep_dir = True

    def _rebuild_session(self) -> None:
        TestHappyPath._session = ProjectSession(self._project_dir, self._project_dir)

    def _assert_clean(self) -> None:
        self.assertFalse(
            Storage(self._project_dir).has_pending(),
            "expected clean working tree but pending changes exist",
        )

    def _assert_pending(self) -> None:
        self.assertTrue(
            Storage(self._project_dir).has_pending(),
            "expected a pending transaction but working tree is clean",
        )

    def _checkpoint(self, msg: str) -> None:
        Storage(self._project_dir).checkpoint(msg)

    # ------------------------------------------------------------------
    # 01 — verify annotation format written by setup_test_project
    # ------------------------------------------------------------------

    def test_01_write_annotation_format(self) -> None:
        """The opening write creates the expected annotation structure."""
        node_md = self._project_dir / "narrative" / "story" / "_node.md"
        text = node_md.read_text()
        self.assertIn("[write", text)
        self.assertIn("Lorem ipsum", text)
        self.assertIn("[/write]: #", text)
        self.assertLess(text.index("Lorem ipsum"), text.index("[/write]: #"))
        self._assert_clean()

    # ------------------------------------------------------------------
    # 02 — kb edit: create new object with AI
    # ------------------------------------------------------------------

    def test_02_kb_edit_with_llm(self) -> None:
        """kb_edit creates a new KB object populated by the fake LLM."""
        # kb_edit is synchronous
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            kb_edit(
                "person.villain", "Create a villain character",
                pins=[], unpins=[], llm_id="mock",
            )
        path = self._project_dir / "knowledge" / "person" / "villain.md"
        self.assertTrue(path.exists())
        self.assertIn("Lorem ipsum", path.read_text())
        self._assert_pending()
        self._checkpoint("kb: add villain")

    # ------------------------------------------------------------------
    # 03 — write fresh then second call errors
    # ------------------------------------------------------------------

    def test_03_write_continue(self) -> None:
        """A second write with no prompt errors (continuation is removed)."""
        self._rebuild_session()
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        # First: a fresh write that we do NOT commit — leaves annotation pending.
        _run_async(WriteOperator.run_inline(
            session=session, narrative=narrative,
            prompt="another scene", pins=[], unpins=[], llm_id="mock", retry=False,
        ))
        self._assert_pending()

        # Second call without prompt now errors.
        with self.assertRaises(OperatorError):
            _run_async(WriteOperator.run_inline(
                session=session, narrative=narrative,
                prompt=None, pins=[], unpins=[], llm_id=None, retry=False,
            ))
        self._assert_pending()

    # ------------------------------------------------------------------
    # 04 — secret encoding: ai:secret: blocks are ROT13-encoded on write
    # ------------------------------------------------------------------

    def test_04_secret_encoding(self) -> None:
        """LLM output containing ai:secret: is ROT13-encoded before storage."""
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        _run_async(WriteOperator.run_inline(
            session=session, narrative=narrative,
            prompt=FAKE_SECRET_TRIGGER,
            pins=[], unpins=[], llm_id="mock", retry=False,
        ))

        text = narrative.find_cursor().md_path().read_text()
        self.assertIn("<!-- ai:secret:", text)
        self.assertIn(FAKE_SECRET_ROT13, text)
        self.assertNotIn("the king betrayed everyone", text)
        self._assert_pending()

    # ------------------------------------------------------------------
    # 05 — section start (creates child node, opens annotation)
    # ------------------------------------------------------------------

    def test_05_section_start(self) -> None:
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        cursor = narrative.find_cursor()
        cursor_md = cursor.md_path()
        rel = str(cursor_md.relative_to(session.git_root))
        storage = session.new_storage(owner=SectionOperator.owner_id("ch1", rel))
        SectionOperator(storage, narrative).start("ch1")

        text = cursor_md.read_text()
        self.assertIn("[section:ch1]: #", text)
        self.assertTrue((self._project_dir / "narrative" / "story" / "ch1.md").exists())
        self._assert_pending()
        self._checkpoint("section: start ch1")

    # ------------------------------------------------------------------
    # 06 — write inside section, commit
    # ------------------------------------------------------------------

    def test_06_write_in_section(self) -> None:
        self._rebuild_session()
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        _run_async(WriteOperator.run_inline(
            session=session, narrative=narrative,
            prompt="write chapter one",
            pins=[], unpins=[], llm_id="mock", retry=False,
        ))

        cursor = narrative.find_cursor()
        text = cursor.md_path().read_text()
        self.assertIn("Lorem ipsum", text)
        self.assertIn("[write", text)
        self._assert_pending()
        self._checkpoint("write: chapter one content")

    # ------------------------------------------------------------------
    # 07 — section end (generates summary, closes annotation on parent)
    # ------------------------------------------------------------------

    def test_07_section_end(self) -> None:
        self._rebuild_session()
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        cursor = narrative.find_cursor()
        key = cursor.key_path[-1]
        parent = NarrativeNode(
            narrative_root=narrative.narrative_root,
            key_path=cursor.key_path[:-1],
        )
        parent_md = parent.md_path()
        rel = str(parent_md.relative_to(session.git_root))
        storage = session.new_storage(owner=SectionOperator.owner_id(key, rel))
        _run_async(SectionOperator(storage, narrative).end(session, llm_id="mock"))

        text = parent_md.read_text()
        self.assertIn("[/section:ch1]: #", text)
        self.assertIn("Lorem ipsum", text)
        self._assert_pending()
        self._checkpoint("section: close ch1")

    # ------------------------------------------------------------------
    # 08 — edit operator: staged claim tags vs working-tree proposal
    # ------------------------------------------------------------------

    def test_08_edit(self) -> None:
        self._rebuild_session()
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        root_node = NarrativeNode(
            narrative_root=narrative.narrative_root, key_path=()
        )
        node_md = root_node.md_path()
        lines = node_md.read_text().splitlines()
        edit_line = next(
            (i + 1 for i, ln in enumerate(lines)
             if ln.strip() and not ln.strip().startswith("[") and not ln.strip().startswith("-")),
            1,
        )
        rel_path = str(node_md.relative_to(session.git_root))

        _run_async(EditOperator.run_mutation(
            session=session, node=root_node, rel_path=rel_path,
            ann_id=f"e{edit_line}_{edit_line}",
            start_line=edit_line, end_line=edit_line,
            prompt="make it more dramatic",
            pins=[], unpins=[], llm_id="mock", retry=False,
        ))

        self._assert_pending()
        staged = subprocess.run(
            ["git", "show", f":0:{rel_path}"],
            cwd=self._project_dir, capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("[edit:", staged)
        self.assertIn("[/edit:", staged)
        self.assertIn("Lorem ipsum", node_md.read_text())

    # ------------------------------------------------------------------
    # 09 — rollback: removes claim tags, restores clean state
    # ------------------------------------------------------------------

    def test_09_rollback(self) -> None:
        self._rebuild_session()
        # execute_rollback is synchronous
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            execute_rollback(self._session)
        self._assert_clean()

        text = (self._project_dir / "narrative" / "story" / "_node.md").read_text()
        self.assertNotIn("[edit:", text)
        self.assertNotIn("[/edit:", text)

    # ------------------------------------------------------------------
    # 10–13 — dataset behaviours (copy-on-write, shadow, delete)
    # ------------------------------------------------------------------

    def test_10_dataset_copy_on_write(self) -> None:
        """Mutating a dataset-only item materialises a local copy."""
        KnowledgeStore.clear_registry()
        self._rebuild_session()
        kb = self._session.kb

        self.assertIsNone(kb.add_tags("person.hero", ["featured"]))

        hero_path = self._project_dir / "knowledge" / "person" / "hero.md"
        self.assertTrue(hero_path.exists())
        tags = kb.get_tags("person.hero")
        self.assertIn("featured", tags)
        self.assertIn("protagonist", tags)
        self._assert_pending()
        self._checkpoint("dataset: copy-on-write person.hero")

    def test_11_dataset_project_shadows_dataset(self) -> None:
        """Project item with the same ID takes precedence over dataset item."""
        kb = self._session.kb
        kb.store_object("person.hero", "A locally overridden hero.")
        obj = kb.get_objects(["person.hero"]).get("person.hero")
        assert obj is not None
        self.assertEqual(obj.text, "A locally overridden hero.")
        self._checkpoint("dataset: project shadows dataset item")

    def test_12_dataset_delete_noop(self) -> None:
        """Deleting a dataset-only item is a silent no-op; item stays visible."""
        kb = self._session.kb
        dungeon_path = self._project_dir / "knowledge" / "place" / "dungeon.md"
        self.assertFalse(dungeon_path.exists())

        kb.delete_object("place.dungeon")

        self.assertFalse(dungeon_path.exists())
        self.assertIsNotNone(kb.get_objects(["place.dungeon"]).get("place.dungeon"))
        self._assert_clean()

    def test_13_dataset_copy_then_delete_local(self) -> None:
        """A dataset item copied locally can then be deleted from the project."""
        kb = self._session.kb
        kb.copy_object("place.dungeon", "place.dungeon_local")
        local_path = self._project_dir / "knowledge" / "place" / "dungeon_local.md"
        self.assertTrue(local_path.exists())
        self._assert_pending()
        self._checkpoint("dataset: copy dungeon to project")

        kb.delete_object("place.dungeon_local")
        self.assertFalse(local_path.exists())
        self._assert_pending()
        self._checkpoint("dataset: delete local copy")


class TestCollateSinglePendingTransaction(unittest.TestCase):
    """Collate is one unstaged pending tx; ``execute_rollback`` restores HEAD."""

    def test_collate_returns_storage_and_rollback_restores(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="lens_itest_collate_"))
        try:
            subprocess.run(
                ["git", "init"], cwd=tmp, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "t@t.com"],
                cwd=tmp,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "T"],
                cwd=tmp,
                capture_output=True,
                check=True,
            )
            (tmp / ".gitkeep").write_text("", encoding="utf-8")
            subprocess.run(
                ["git", "add", "-A"], cwd=tmp, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmp,
                capture_output=True,
                check=True,
            )
            (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\n', encoding="utf-8")
            narrative_dir = tmp / "narrative" / "story"
            narrative_dir.mkdir(parents=True)
            original = "One.\nTwo.\nThree.\n"
            (narrative_dir / "_node.md").write_text(original, encoding="utf-8")
            (tmp / "knowledge").mkdir(exist_ok=True)
            subprocess.run(
                ["git", "add", "-A"], cwd=tmp, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "content"],
                cwd=tmp,
                capture_output=True,
                check=True,
            )

            session = ProjectSession(tmp, tmp)
            narrative = NarrativeNode(narrative_root=narrative_dir, key_path=())

            async def _fake_summary(*args: object, **kwargs: object) -> str:
                if kwargs.get("operator_name") == "remember":
                    return ""
                return "Summary block."

            with patch(
                "lens.core.operators.session.generate_text",
                new=_fake_summary,
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    st = _run_async(
                        CollateOperator.run_collate(
                            session=session,
                            narrative=narrative,
                            id="boxed",
                            address_str="story",
                            start_line=2,
                            end_line=2,
                            pins=[],
                            unpins=[],
                            llm_id=None,
                        )
                    )

            self.assertIsInstance(st, Storage)
            self.assertTrue(st.has_pending())
            self.assertFalse(st.has_staged())

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                execute_rollback(session)

            self.assertFalse(Storage(tmp).has_pending())
            self.assertEqual(narrative.md_path().read_text(encoding="utf-8"), original)
            self.assertFalse(narrative.child_node("boxed").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
