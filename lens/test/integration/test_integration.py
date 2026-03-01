"""Full-stack happy-path regression test for Lens.

Spins up a tiny fake LLM HTTP server that returns Lorem Ipsum text, creates a
temporary git project, drives every core feature through the public Python API,
and verifies git state at each step.

The temp directory is preserved for inspection when any step fails.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from collections.abc import Coroutine
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, TypeVar

from lens.core.commands.init import init_project
from lens.core.commands.kb import kb_add, kb_tag
from lens.core.commands.pin import pin_add
from lens.core.commands.rollback import execute_rollback
from lens.core.commands.use import use_narrative
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operators.edit import EditOperator
from lens.cli.operators.section import _section_start  # pyright: ignore[reportPrivateUsage]
from lens.core.operators.section import SectionOperator
from lens.core.operators.write import WriteOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# Fake LLM server
# ---------------------------------------------------------------------------

_LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris."
)

_EMIT_SECRET_PROMPT = "EMIT_AI_SECRET"
_SECRET_PLAINTEXT = "the king betrayed everyone"
_SECRET_ROT13 = "gur xvat orgenlrq rirelbar"


class _FakeLLMHandler(BaseHTTPRequestHandler):
    """Serve one fake SSE streaming completion per POST request."""

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data: dict[str, Any] = json.loads(body) if body else {}
            messages: list[dict[str, Any]] = data.get("messages", [])
            total_chars = sum(len(m.get("content", "")) for m in messages)
            msg_text = " ".join(m.get("content", "") for m in messages)
            if _EMIT_SECRET_PROMPT in msg_text:
                response_text = (
                    f"{_LOREM}\n\n<!-- ai:secret:\n{_SECRET_PLAINTEXT}\n-->"
                )
            else:
                response_text = f"{_LOREM} [input:{total_chars}]"

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            for word in response_text.split():
                chunk = json.dumps({
                    "choices": [{"delta": {"content": word + " "}, "finish_reason": None}]
                })
                self.wfile.write(f"data: {chunk}\n\n".encode())
                self.wfile.flush()

            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass

    def log_message(self, format: str, *args: Any) -> None:  # silence server logs
        pass


class _FakeLLMServer:
    def __init__(self) -> None:
        self._server = HTTPServer(("127.0.0.1", 0), _FakeLLMHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        addr = self._server.server_address
        return f"http://{addr[0]}:{addr[1]}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)


def _quiet(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Call fn(*args, **kwargs) swallowing stdout and stderr."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def _quiet_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run a coroutine swallowing stdout and stderr."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Integration test suite
# ---------------------------------------------------------------------------

class TestHappyPath(unittest.TestCase):
    """Sequential happy-path regression across all core Lens features.

    Methods are prefixed test_NN_ to enforce execution order (unittest sorts
    methods alphabetically).  Each step depends on the state left by the
    previous one.  If any step fails the temporary project directory is
    preserved for inspection.
    """

    _server: _FakeLLMServer
    _project_dir: Path
    _orig_cwd: Path
    _keep_dir: bool = False
    _session: ProjectSession

    @classmethod
    def setUpClass(cls) -> None:
        cls._server = _FakeLLMServer()
        cls._server.start()

        cls._project_dir = Path(tempfile.mkdtemp(prefix="lens_itest_"))
        cls._orig_cwd = Path.cwd()
        os.chdir(cls._project_dir)

        _git(cls._project_dir, "init")
        _git(cls._project_dir, "config", "user.email", "test@test.com")
        _git(cls._project_dir, "config", "user.name", "Test")
        (cls._project_dir / ".gitkeep").write_text("")
        _git(cls._project_dir, "add", "-A")
        _git(cls._project_dir, "commit", "-m", "root")

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
            failures = getattr(result, "failures", [])
            errors = getattr(result, "errors", [])
            if failures or errors:
                TestHappyPath._keep_dir = True

    # --- Shared helpers ---

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
    # 01 — init project, select narrative, configure mock LLM
    # ------------------------------------------------------------------

    def test_01_init_and_setup(self) -> None:
        import tomllib
        import tomli_w

        _quiet(init_project)
        _quiet(use_narrative, "story")

        # Patch lens.toml to add the mock LLM entry and enable the testing dataset.
        lens_toml = self._project_dir / "lens.toml"
        with lens_toml.open("rb") as fh:
            cfg = tomllib.load(fh)
        cfg["llm"] = [{"id": "mock", "base_url": self._server.base_url, "model": "mock"}]
        if isinstance(cfg.get("project"), dict):
            cfg["project"]["datasets"] = ["testing"]
        with io.BytesIO() as buf:
            tomli_w.dump(cfg, buf)
            lens_toml.write_bytes(buf.getvalue())

        Storage(self._project_dir).stage_all()
        _git(self._project_dir, "commit", "-m", "init: project setup")

        self._rebuild_session()
        self._assert_clean()

        self.assertTrue(lens_toml.exists())
        self.assertTrue((self._project_dir / "knowledge").is_dir())
        self.assertTrue((self._project_dir / "narrative" / "story").is_dir())
        narrative = self._session.active_narrative
        self.assertIsNotNone(narrative)
        assert narrative is not None
        self.assertEqual(narrative.narrative_root.name, "story")

    # ------------------------------------------------------------------
    # 02 — create KB objects
    # ------------------------------------------------------------------

    def test_02_kb_objects(self) -> None:
        _quiet(kb_add, "person.amy", "Amy is the brave protagonist.", False)
        _quiet(kb_add, "place.forest", "A dark and ancient forest.", False)

        self.assertTrue((self._project_dir / "knowledge" / "person" / "amy.md").exists())
        self.assertTrue((self._project_dir / "knowledge" / "place" / "forest.md").exists())
        self._assert_pending()

    # ------------------------------------------------------------------
    # 03 — tag KB objects and commit
    # ------------------------------------------------------------------

    def test_03_kb_tags_and_commit(self) -> None:
        import tomllib

        _quiet(kb_tag, "person.amy", ["protagonist"], [])

        tags_toml = self._project_dir / "knowledge" / "tags.toml"
        with tags_toml.open("rb") as fh:
            tags = tomllib.load(fh)
        self.assertIn("person.amy", tags.get("objects", {}))

        self._checkpoint("kb: add characters and places")
        self._assert_clean()

    # ------------------------------------------------------------------
    # 04 — pin KB object to cursor node, commit
    # ------------------------------------------------------------------

    def test_04_pin_and_commit(self) -> None:
        session = self._session
        _quiet(pin_add, session, "person.amy", None, [], None)

        node_md = self._project_dir / "narrative" / "story" / "_node.md"
        text = node_md.read_text()
        self.assertIn("person.amy", text)
        self._assert_pending()

        self._checkpoint("pin: person.amy on root node")
        self._assert_clean()

    # ------------------------------------------------------------------
    # 05 — write operator (fresh generation)
    # ------------------------------------------------------------------

    def test_05_write_fresh(self) -> None:
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        _quiet_async(WriteOperator.run_inline(
            session=session,
            narrative=narrative,
            prompt="begin the story",
            pins=[],
            unpins=[],
            llm_id="mock",
            retry=False,
        ))

        node_md = self._project_dir / "narrative" / "story" / "_node.md"
        text = node_md.read_text()
        self.assertIn("[write", text)
        self.assertIn("steps: 1", text)
        self.assertIn("Lorem ipsum", text)
        self.assertIn("[/write]: #", text)
        self.assertLess(text.index("Lorem ipsum"), text.index("[/write]: #"))
        self._assert_pending()

    # ------------------------------------------------------------------
    # 06 — write operator (continue: same annotation, steps incremented)
    # ------------------------------------------------------------------

    def test_06_write_continue(self) -> None:
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        _quiet_async(WriteOperator.run_inline(
            session=session,
            narrative=narrative,
            prompt=None,
            pins=[],
            unpins=[],
            llm_id=None,
            retry=False,
        ))

        text = (self._project_dir / "narrative" / "story" / "_node.md").read_text()
        self.assertIn("steps: 2", text)
        self.assertEqual(text.count("[/write]: #"), 1)
        self._assert_pending()

    # ------------------------------------------------------------------
    # 07 — commit the write transaction
    # ------------------------------------------------------------------

    def test_07_commit_write(self) -> None:
        self._checkpoint("write: opening passage")
        self._assert_clean()

    def test_07b_emitted_secrets_encoded(self) -> None:
        """LLM output containing ai:secret: blocks is ROT13-encoded before storage."""
        self._rebuild_session()
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        _quiet_async(WriteOperator.run_inline(
            session=session,
            narrative=narrative,
            prompt=_EMIT_SECRET_PROMPT,
            pins=[],
            unpins=[],
            llm_id="mock",
            retry=False,
        ))

        text = narrative.find_cursor().md_path().read_text()
        self.assertIn("<!-- ai:secret:", text)
        self.assertIn(_SECRET_ROT13, text)
        self.assertNotIn(_SECRET_PLAINTEXT, text)
        self._assert_pending()

    # ------------------------------------------------------------------
    # 08 — section start (creates child node, opens annotation)
    # ------------------------------------------------------------------

    def test_08_section_start(self) -> None:
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        cursor = narrative.find_cursor()
        cursor_md = cursor.md_path()
        rel = str(cursor_md.relative_to(session.git_root))
        owner = SectionOperator.owner_id("ch1", rel)
        storage = session.new_storage(owner=owner)
        op = SectionOperator(storage, narrative)
        op.start("ch1")

        text = cursor_md.read_text()
        self.assertIn("[section:ch1]: #", text)
        self.assertTrue((self._project_dir / "narrative" / "story" / "ch1.md").exists())
        self._assert_pending()

        self._checkpoint("section: start ch1")
        self._assert_clean()

    # ------------------------------------------------------------------
    # 09 — write inside section, commit
    # ------------------------------------------------------------------

    def test_09_write_in_section(self) -> None:
        self._rebuild_session()
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        _quiet_async(WriteOperator.run_inline(
            session=session,
            narrative=narrative,
            prompt="write chapter one",
            pins=[],
            unpins=[],
            llm_id="mock",
            retry=False,
        ))

        cursor = narrative.find_cursor()
        text = cursor.md_path().read_text()
        self.assertIn("Lorem ipsum", text)
        self.assertIn("[write", text)
        self._assert_pending()

        self._checkpoint("write: chapter one content")
        self._assert_clean()

    # ------------------------------------------------------------------
    # 10 — section end (generates summary, closes annotation)
    # ------------------------------------------------------------------

    def test_10_section_end(self) -> None:
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
        owner = SectionOperator.owner_id(key, rel)
        storage = session.new_storage(owner=owner)
        op = SectionOperator(storage, narrative)

        _quiet_async(op.end(session, llm_id="mock"))

        text = parent_md.read_text()
        self.assertIn("[/section:ch1]: #", text)
        self.assertIn("Lorem ipsum", text)  # summary content
        self._assert_pending()

        self._checkpoint("section: close ch1")
        self._assert_clean()

    # ------------------------------------------------------------------
    # 11 — edit operator (claims a line range, proposes replacement)
    # ------------------------------------------------------------------

    def test_11_edit(self) -> None:
        self._rebuild_session()
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None

        root_node = NarrativeNode(
            narrative_root=narrative.narrative_root, key_path=()
        )
        node_md = root_node.md_path()
        lines = node_md.read_text().splitlines()

        # Find the first non-blank, non-annotation content line to edit.
        edit_line = next(
            (i + 1 for i, ln in enumerate(lines)
             if ln.strip() and not ln.strip().startswith("[") and not ln.strip().startswith("-")),
            1,
        )
        rel_path = str(node_md.relative_to(session.git_root))
        ann_id = f"e{edit_line}_{edit_line}"

        _quiet_async(EditOperator.run_mutation(
            session=session,
            node=root_node,
            rel_path=rel_path,
            ann_id=ann_id,
            start_line=edit_line,
            end_line=edit_line,
            prompt="make it more dramatic",
            pins=[],
            unpins=[],
            llm_id="mock",
            retry=False,
        ))

        self._assert_pending()

        # Staged version (claim tags) should contain the edit annotation.
        staged = subprocess.run(
            ["git", "show", f":0:{rel_path}"],
            cwd=self._project_dir, capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("[edit:", staged)
        self.assertIn("[/edit:", staged)

        # Working-tree version (proposal) should have the LLM content.
        self.assertIn("Lorem ipsum", node_md.read_text())

    # ------------------------------------------------------------------
    # 12 — rollback edit (compensating transaction removes claim tags)
    # ------------------------------------------------------------------

    def test_12_rollback(self) -> None:
        self._rebuild_session()
        session = self._session

        _quiet(execute_rollback, session)

        self._assert_clean()

        # Claim tags should be gone; original content restored.
        node_md = self._project_dir / "narrative" / "story" / "_node.md"
        text = node_md.read_text()
        self.assertNotIn("[edit:", text)
        self.assertNotIn("[/edit:", text)

    # ------------------------------------------------------------------
    # 13 — dataset lookup: items from the "testing" dataset are visible
    # ------------------------------------------------------------------

    def test_13_dataset_lookup(self) -> None:
        # The "testing" dataset was activated in test_01_init_and_setup.
        # Clear registry so the store is rebuilt with datasets from lens.toml.
        KnowledgeStore.clear_registry()
        self._rebuild_session()
        kb = self._session.kb

        # Dataset items are visible even though they are not in the project.
        hero = kb.get_objects(["person.hero"]).get("person.hero")
        dungeon = kb.get_objects(["place.dungeon"]).get("place.dungeon")
        self.assertIsNotNone(hero, "person.hero should be visible from testing dataset")
        self.assertIsNotNone(dungeon, "place.dungeon should be visible from testing dataset")
        assert hero is not None
        assert dungeon is not None
        self.assertIn("hero", hero.text)
        self.assertIn("dungeon", dungeon.text)

        # Tags defined in the dataset's tags.toml are surfaced correctly.
        self.assertIn("protagonist", hero.tags)
        self.assertIn("place.dungeon", hero.tags)

        # Dataset items should NOT be present as local project files.
        self.assertFalse(
            (self._project_dir / "knowledge" / "person" / "hero.md").exists(),
            "dataset item should not be copied to project on plain read",
        )

    # ------------------------------------------------------------------
    # 14 — copy-on-write: mutating a dataset item creates a local copy
    # ------------------------------------------------------------------

    def test_14_dataset_copy_on_write(self) -> None:
        kb = self._session.kb

        # Add a tag to the dataset item — this should trigger copy-on-write.
        err = kb.add_tags("person.hero", ["featured"])
        self.assertIsNone(err)

        hero_path = self._project_dir / "knowledge" / "person" / "hero.md"
        self.assertTrue(
            hero_path.exists(),
            "copy-on-write should have materialised person.hero in the project",
        )
        self.assertIn("hero", hero_path.read_text())

        # The project's tags.toml should carry both the original dataset tags
        # and the new one.
        tags = kb.get_tags("person.hero")
        self.assertIn("featured", tags)
        self.assertIn("protagonist", tags)

        self._assert_pending()
        self._checkpoint("dataset: copy-on-write person.hero")
        self._assert_clean()

    # ------------------------------------------------------------------
    # 15 — project item shadows dataset item with the same id
    # ------------------------------------------------------------------

    def test_15_dataset_project_shadows_dataset(self) -> None:
        kb = self._session.kb

        # Overwrite the local copy of person.hero with different content.
        kb.store_object("person.hero", "A locally overridden hero.")
        hero_path = self._project_dir / "knowledge" / "person" / "hero.md"
        self.assertEqual(hero_path.read_text(), "A locally overridden hero.")

        # The project version should win on lookup.
        obj = kb.get_objects(["person.hero"]).get("person.hero")
        self.assertIsNotNone(obj)
        assert obj is not None
        self.assertEqual(obj.text, "A locally overridden hero.")

        self._checkpoint("dataset: project shadows dataset item")
        self._assert_clean()

    # ------------------------------------------------------------------
    # 16 — delete no-op: deleting a dataset-only item does nothing
    # ------------------------------------------------------------------

    def test_16_dataset_delete_noop(self) -> None:
        kb = self._session.kb

        # place.dungeon is dataset-only (never been copied locally).
        dungeon_path = self._project_dir / "knowledge" / "place" / "dungeon.md"
        self.assertFalse(dungeon_path.exists())

        # Delete should be a silent no-op.
        kb.delete_object("place.dungeon")
        self.assertFalse(dungeon_path.exists())

        # The item is still visible from the dataset after the no-op delete.
        dungeon = kb.get_objects(["place.dungeon"]).get("place.dungeon")
        self.assertIsNotNone(dungeon, "dataset item should still be visible after no-op delete")

        # No changes pending (the no-op delete wrote nothing to the project).
        self._assert_clean()

    # ------------------------------------------------------------------
    # 17 — copy from dataset to project, then delete local copy
    # ------------------------------------------------------------------

    def test_17_dataset_copy_then_delete_local(self) -> None:
        kb = self._session.kb

        # Copy a dataset item into the project under a new id.
        kb.copy_object("place.dungeon", "place.dungeon_local")
        local_path = self._project_dir / "knowledge" / "place" / "dungeon_local.md"
        self.assertTrue(local_path.exists())
        self.assertIn("dungeon", local_path.read_text())
        self._assert_pending()
        self._checkpoint("dataset: copy dungeon to project")
        self._assert_clean()

        # Deleting the local copy IS allowed (it's a project item now).
        kb.delete_object("place.dungeon_local")
        self.assertFalse(local_path.exists())
        self._assert_pending()
        self._checkpoint("dataset: delete local copy")
        self._assert_clean()


class TestSectionStartWithWriteChain(unittest.TestCase):
    """Integration test: section start --write chains write after section."""

    _server: _FakeLLMServer
    _project_dir: Path
    _orig_cwd: Path
    _session: ProjectSession

    @classmethod
    def setUpClass(cls) -> None:
        import tomllib
        import tomli_w

        cls._server = _FakeLLMServer()
        cls._server.start()
        cls._project_dir = Path(tempfile.mkdtemp(prefix="lens_chain_"))
        cls._orig_cwd = Path.cwd()
        os.chdir(cls._project_dir)
        _git(cls._project_dir, "init")
        _git(cls._project_dir, "config", "user.email", "test@test.com")
        _git(cls._project_dir, "config", "user.name", "Test")
        (cls._project_dir / ".gitkeep").write_text("")
        _git(cls._project_dir, "add", "-A")
        _git(cls._project_dir, "commit", "-m", "root")
        _quiet(init_project)
        _quiet(use_narrative, "story")
        lens_toml = cls._project_dir / "lens.toml"
        with lens_toml.open("rb") as fh:
            cfg = tomllib.load(fh)
        cfg["llm"] = [{"id": "mock", "base_url": cls._server.base_url, "model": "mock"}]
        with io.BytesIO() as buf:
            tomli_w.dump(cfg, buf)
            lens_toml.write_bytes(buf.getvalue())
        Storage(cls._project_dir).stage_all()
        _git(cls._project_dir, "commit", "-m", "init")
        cls._session = ProjectSession(cls._project_dir, cls._project_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        os.chdir(cls._orig_cwd)
        cls._server.stop()
        shutil.rmtree(str(cls._project_dir), ignore_errors=True)

    def test_section_start_with_write_chains_write(self) -> None:
        session = self._session
        narrative = session.active_narrative
        assert narrative is not None
        _quiet(_section_start, session, narrative, "ch1", write_prompt="opening scene")
        parent = self._project_dir / "narrative" / "story" / "_node.md"
        text = parent.read_text()
        self.assertIn("[section:ch1]: #", text)
        child_md = self._project_dir / "narrative" / "story" / "ch1.md"
        self.assertTrue(child_md.exists())
        child_text = child_md.read_text()
        self.assertIn("[write", child_text)
        self.assertIn("Lorem ipsum", child_text)
