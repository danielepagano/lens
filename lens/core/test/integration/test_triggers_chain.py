"""The trigger chain end to end against the fake LLM (#195).

Prep declares ``design-cellar``; a marker in the passage offers it; firing it
opens ``design-cellar-tr``; the design session declares the follow-up
``play-cellar`` on the opener's object (no ``id`` given) and suggests it;
``--end`` writes the suggestion into the parent after the close tag, and the
parent is offered the follow-up.  Sequential: state accumulates.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lens.core.annotations import strip_markdown_comments
from lens.core.commands.kb import KbMaterializeResult
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.operators.design import DesignOperator
from lens.core.pinning import pin
from lens.core.project import ProjectSession
from lens.core.triggers import fire_trigger, fired_slugs, open_offers, triggers_from_text
from lens.testing.fake_llm import KB_OP_TRIGGER, FakeLLMServer
from lens.testing.project import setup_test_project

PREP = (
    "[\n"
    "    triggers:\n"
    "      design-cellar:\n"
    "        when: Enso opens the store cellar hatch\n"
    "        run: design\n"
    "]: #\n"
    "\n"
    "The village store. Its cellar is held back.\n"
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TestTriggerChain(unittest.TestCase):
    _server: FakeLLMServer
    _dir: Path
    _cwd: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._server = FakeLLMServer()
        cls._server.start()
        cls._dir = Path(tempfile.mkdtemp(prefix="lens_triggers_"))
        cls._cwd = Path.cwd()
        session = setup_test_project(cls._dir, cls._server.base_url, dataset="testing")
        (cls._dir / "knowledge" / "prep").mkdir(parents=True, exist_ok=True)
        (cls._dir / "knowledge" / "prep" / "store.md").write_text(PREP)
        narrative = session.active_narrative
        assert narrative is not None
        storage = session.new_storage()
        pin(narrative, ["prep.store"], storage)
        storage.stage_all()
        os.chdir(cls._dir)

    @classmethod
    def tearDownClass(cls) -> None:
        os.chdir(cls._cwd)
        cls._server.stop()
        shutil.rmtree(str(cls._dir), ignore_errors=True)

    def _session(self) -> ProjectSession:
        KnowledgeStore.clear_registry()
        return ProjectSession(self._dir, self._dir)

    def _narrative(self, session: ProjectSession) -> NarrativeNode:
        n = session.active_narrative
        assert n is not None
        return n

    def test_01_a_marker_in_the_passage_is_an_offer(self) -> None:
        session = self._session()
        narrative = self._narrative(session)
        root_md = narrative.find_cursor().md_path()
        root_md.write_text(root_md.read_text().rstrip("\n") + "\n\n<!-- suggest:design-cellar -->\n")
        offers = open_offers(session.kb, narrative)
        self.assertEqual([o.slug for o in offers], ["design-cellar"])

    def test_02_firing_opens_the_tr_node_and_ends_the_offer(self) -> None:
        session = self._session()
        narrative = self._narrative(session)
        calls = [
            {
                "tool": "kb_set_trigger",
                "arguments": {
                    "slug": "cellar",
                    "when": "Enso stands at the open hatch",
                    "run": "play --pin prep.store",
                },
            },
            {"tool": "suggest_trigger", "arguments": {"slug": "play-cellar"}},
        ]
        prompt = f"{KB_OP_TRIGGER} {json.dumps(calls)}"
        # The stored run is a bare `design`; this firing edits it, as `e` would.
        _run(fire_trigger(
            session=session, narrative=narrative, slug="design-cellar",
            run=f"design {shlex.quote(prompt)}",
        ))
        cursor = self._narrative(self._session()).find_cursor()
        self.assertEqual(cursor.key_path, ("design-cellar-tr",))
        text = cursor.md_path().read_text()
        self.assertIn("op: trigger", text)
        self.assertIn("id: prep.store", text)  # defaulted to the opener's object
        self.assertIn("op: suggest", text)
        self.assertIn("design-cellar", fired_slugs(cursor.narrative_root))
        # Nothing reached disk yet: proposals until --end.
        on_disk = (self._dir / "knowledge" / "prep" / "store.md").read_text()
        self.assertNotIn("play-cellar", on_disk)

    def test_03_end_writes_the_trigger_and_offers_the_follow_up(self) -> None:
        session = self._session()
        narrative = self._narrative(session)
        result = _run(DesignOperator.run_session(
            session=session, narrative=narrative, pins=[], unpins=[], end=True,
        ))
        self.assertIsInstance(result, KbMaterializeResult)
        self.assertEqual(result.offered, ["play-cellar"])
        self.assertEqual(result.offer_errors, [])

        on_disk = (self._dir / "knowledge" / "prep" / "store.md").read_text()
        found = triggers_from_text(on_disk, "prep.store")
        self.assertEqual(set(found), {"design-cellar", "play-cellar"})
        self.assertEqual(found["play-cellar"].run, "play --pin prep.store --pass")
        self.assertIn("The village store.", strip_markdown_comments(on_disk))

        session = self._session()
        narrative = self._narrative(session)
        cursor = narrative.find_cursor()
        self.assertEqual(cursor.key_path, ())  # an HTML comment is not an annotation
        tail = cursor.md_path().read_text().rstrip("\n").split("\n")
        self.assertEqual(tail[-1], "<!-- suggest:play-cellar -->")
        self.assertEqual(tail[-2], "[/design:design-cellar-tr]: #")
        self.assertEqual([o.slug for o in open_offers(session.kb, narrative)], ["play-cellar"])


if __name__ == "__main__":
    unittest.main()
