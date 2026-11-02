"""``lens trigger`` and the post-turn offer, through the real CLI (#195).

Run as subprocesses, so stdin/stdout are pipes: the offer must print a hint
naming ``lens trigger <slug>`` rather than block on a prompt.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lens.testing.fake_llm import FakeLLMServer

_LENS_CMD = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]

PREP = (
    "[\n"
    "    triggers:\n"
    "      design-cellar:\n"
    "        when: Enso opens the store cellar hatch\n"
    "        run: design\n"
    "      design-loft:\n"
    "        when: Enso climbs to the loft\n"
    "        run: design\n"
    "]: #\n"
    "\n"
    "The village store.\n"
)

SUGGEST_LOFT = "\n[kb-op\n  op: suggest\n  slug: design-loft\n]: #\n"


def _lens(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_LENS_CMD, *args], cwd=project, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )


class TestTriggerCli(unittest.TestCase):
    server: FakeLLMServer
    project: Path

    @classmethod
    def setUpClass(cls) -> None:
        from lens.core.pinning import pin
        from lens.testing.project import setup_test_project

        cls.server = FakeLLMServer()
        cls.server.start()
        cls.project = Path(tempfile.mkdtemp(prefix="lens_trigger_cli_"))
        session = setup_test_project(cls.project, cls.server.base_url, opening_write=False)
        (cls.project / "knowledge" / "prep").mkdir(parents=True, exist_ok=True)
        (cls.project / "knowledge" / "prep" / "store.md").write_text(PREP)
        narrative = session.active_narrative
        assert narrative is not None
        storage = session.new_storage()
        pin(narrative, ["prep.store"], storage)
        md = narrative.md_path()
        md.write_text(md.read_text().rstrip("\n") + "\n\nEnso reaches the hatch.\n\n<!-- suggest:design-cellar -->\n")
        storage.stage_all()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(str(cls.project), ignore_errors=True)

    def test_01_lists_offers_and_all_open_triggers(self) -> None:
        out = _lens(self.project, "trigger")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("design-cellar", out.stdout)
        self.assertNotIn("design-loft", out.stdout)
        every = _lens(self.project, "trigger", "--all")
        self.assertIn("design-loft", every.stdout)
        stats = _lens(self.project, "stats")
        self.assertIn("Offer: design-cellar", stats.stdout)

    def test_02_unknown_slug_fails_cleanly(self) -> None:
        out = _lens(self.project, "trigger", "design-nope")
        self.assertEqual(out.returncode, 1)
        self.assertIn("no trigger 'design-nope' is declared", out.stderr)
        self.assertNotIn("Traceback", out.stderr)

    def test_03_running_opens_the_tr_session(self) -> None:
        out = _lens(self.project, "trigger", "design-cellar")
        self.assertEqual(out.returncode, 0, out.stderr)
        child = self.project / "narrative" / "story" / "design-cellar-tr.md"
        self.assertTrue(child.exists())
        self.assertNotIn("Offer: design-cellar", out.stderr)
        again = _lens(self.project, "trigger", "design-cellar")
        self.assertEqual(again.returncode, 1)
        self.assertIn("already done", again.stderr)

    def test_04_end_offers_as_a_hint_off_a_terminal(self) -> None:
        child = self.project / "narrative" / "story" / "design-cellar-tr.md"
        child.write_text(child.read_text().rstrip("\n") + "\n" + SUGGEST_LOFT)
        out = _lens(self.project, "design", "--end")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Offer: design-loft", out.stderr)
        self.assertIn("lens trigger design-loft", out.stderr)
        root = (self.project / "narrative" / "story" / "_node.md").read_text()
        self.assertTrue(root.rstrip().endswith("<!-- suggest:design-loft -->"))


if __name__ == "__main__":
    unittest.main()
