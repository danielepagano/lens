"""Advance can suggest a trigger (#195): it sees [HELD BACK], suggests, and its close offers.

Triggers never *run* advance (that would be a recurring trigger, out of scope),
but advance is how a held-back moment arrives off-screen: the jump brings it
about, so advance cuts there and suggests the trigger for the player to run.
The fake LLM's tool-call cue is planted in the pinned prep object, so it reaches
the model the way any prep text would.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from lens.core.context import CrawlSpec, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.pinning import pin
from lens.core.project import ProjectSession
from lens.core.triggers import open_offers
from lens.rpg.operators.advance import AdvanceOperator
from lens.testing.fake_llm import KB_OP_TRIGGER, FakeLLMServer
from lens.testing.regression_fixtures import setup_advance_minimal

_CUE = json.dumps({"tool": "suggest_trigger", "arguments": {"slug": "design-turning"}})

PREP = (
    "[\n"
    "    triggers:\n"
    "      design-turning:\n"
    "        when: Phent moves on the mill in the night\n"
    "        run: design --pin prep.vale \"Build the Turning against the state the vale is in.\"\n"
    "]: #\n"
    "\n"
    "The vale around the mill pond.\n"
    f"{KB_OP_TRIGGER} {_CUE}\n"
)


class TestAdvanceSuggestsTriggers(unittest.TestCase):
    _server: FakeLLMServer
    _dir: Path
    _cwd: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._server = FakeLLMServer()
        cls._server.start()
        cls._dir = Path(tempfile.mkdtemp(prefix="lens_triggers_advance_"))
        cls._cwd = Path.cwd()
        session = setup_advance_minimal(cls._dir, cls._server.base_url)
        (cls._dir / "knowledge" / "prep").mkdir(parents=True, exist_ok=True)
        (cls._dir / "knowledge" / "prep" / "vale.md").write_text(PREP)
        narrative = session.active_narrative
        assert narrative is not None
        storage = session.new_storage()
        pin(narrative, ["prep.vale"], storage)
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

    def test_01_advance_sees_the_held_back_block(self) -> None:
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        op = AdvanceOperator(session.new_storage(), narrative)
        result = crawl(CrawlSpec.of(narrative.find_cursor()))
        user = op.build_messages(result, {"increment": 1}, session=session, narrative=narrative)[-1][
            "content"
        ]
        self.assertIn("--- begin HELD BACK ---", user)
        self.assertIn("- design-turning: Phent moves on the mill in the night", user)
        self.assertIn("treat it as a beat under INTERRUPTIONS", user)  # advance's own text
        self.assertNotIn("Build the Turning", user)  # the run never reaches the model

    def test_02_the_jump_suggests_and_the_close_offers(self) -> None:
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        asyncio.run(AdvanceOperator.run_advance(
            session=session, narrative=narrative, increment=1, pins=[], unpins=[]
        ))
        child = self._session().active_narrative
        assert child is not None
        child_text = child.find_cursor().md_path().read_text()
        self.assertIn("op: suggest", child_text)
        self.assertIn("slug: design-turning", child_text)

        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        result = asyncio.run(AdvanceOperator.run_advance(
            session=session, narrative=narrative, pins=[], unpins=[], end=True
        ))
        self.assertEqual(result.offered, ["design-turning"])
        session = self._session()
        narrative = session.active_narrative
        assert narrative is not None
        cursor = narrative.find_cursor()
        self.assertEqual(cursor.key_path, ())
        self.assertEqual(
            cursor.md_path().read_text().rstrip("\n").split("\n")[-1],
            "<!-- suggest:design-turning -->",
        )
        self.assertEqual([o.slug for o in open_offers(session.kb, narrative)], ["design-turning"])


if __name__ == "__main__":
    unittest.main()
