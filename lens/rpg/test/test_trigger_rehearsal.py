"""``lens test-play --trigger``: real play beats, in memory, read back for markers.

The fake LLM's ``EMIT_REPLY`` cue rides in the player line, so each test decides
what play "says" and checks what the rehearsal reports, and that nothing is
written.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lens.core.exceptions import ValidationError
from lens.core.knowledge import KnowledgeStore
from lens.core.pinning import pin
from lens.core.project import ProjectSession
from lens.rpg.trigger_rehearsal import RehearsalResult, prepare_rehearsal, rehearse_trigger
from lens.testing.fake_llm import REPLY_TRIGGER, FakeLLMServer
from lens.testing.regression_fixtures import setup_rpg_play_pins

PREP = (
    "[\n"
    "    triggers:\n"
    "      design-cellar:\n"
    "        when: Elena opens the store cellar hatch\n"
    "        run: design --pin prep.store\n"
    "      design-loft:\n"
    "        when: Elena climbs to the loft\n"
    "        run: design --pin prep.store\n"
    "]: #\n"
    "\n"
    "The village store.\n"
)

HALL = (
    "[\n"
    "    triggers:\n"
    "      design-hall-glow:\n"
    "        when: Elena sees the glow under the hall door before first light\n"
    "        run: design --pin prep.hall\n"
    "]: #\n"
    "\n"
    "The elder's hall, not yet reached in the story.\n"
)

_LENS = [sys.executable, "-W", "ignore::SyntaxWarning:pysbd", "-m", "lens.cli.main"]


def _cue(text: str) -> str:
    return f"I open the hatch. {REPLY_TRIGGER} {json.dumps(text)}"


class TestTriggerRehearsal(unittest.TestCase):
    _server: FakeLLMServer
    _dir: Path
    _cwd: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._server = FakeLLMServer()
        cls._server.start()
        cls._dir = Path(tempfile.mkdtemp(prefix="lens_rehearsal_"))
        cls._cwd = Path.cwd()
        session = setup_rpg_play_pins(cls._dir, cls._server.base_url)
        (cls._dir / "knowledge" / "prep").mkdir(parents=True, exist_ok=True)
        (cls._dir / "knowledge" / "prep" / "store.md").write_text(PREP)
        # Prep for a scene the story has not reached: declared, pinned nowhere.
        (cls._dir / "knowledge" / "prep" / "hall.md").write_text(HALL)
        narrative = session.active_narrative
        assert narrative is not None
        storage = session.new_storage()
        pin(narrative, ["prep.store"], storage)
        storage.stage_all()
        subprocess.run(["git", "commit", "-qm", "prep"], cwd=cls._dir, check=True)
        os.chdir(cls._dir)

    @classmethod
    def tearDownClass(cls) -> None:
        os.chdir(cls._cwd)
        cls._server.stop()
        shutil.rmtree(str(cls._dir), ignore_errors=True)

    def _run(self, **kw: Any) -> RehearsalResult:
        KnowledgeStore.clear_registry()
        session = ProjectSession(self._dir, self._dir)
        narrative = session.active_narrative
        assert narrative is not None
        return asyncio.run(rehearse_trigger(session=session, narrative=narrative, **kw))

    def _status(self) -> str:
        return subprocess.run(
            ["git", "status", "--porcelain"], cwd=self._dir, capture_output=True, text=True
        ).stdout

    def test_a_beat_that_suggests_counts_and_writes_nothing(self) -> None:
        before = self._status()
        result = self._run(
            slug="design-cellar",
            prompt=_cue("You lift the hatch.\n\n<!-- suggest:design-cellar -->"),
            repeat=2,
        )
        self.assertEqual(result.hits, 2)
        self.assertEqual(result.runs[0].markers, ["design-cellar"])
        self.assertEqual(self._status(), before)

    def test_a_miss_and_a_wrong_marker_are_reported(self) -> None:
        miss = self._run(slug="design-cellar", prompt=_cue("You lift the hatch. Below: barrels."))
        self.assertEqual(miss.hits, 0)
        self.assertEqual(miss.runs[0].markers, [])
        wrong = self._run(slug="design-cellar", prompt=_cue("Up you go.\n<!-- suggest:design-loft -->"))
        self.assertEqual(wrong.hits, 0)
        self.assertEqual(wrong.runs[0].others("design-cellar"), ["design-loft"])

    def test_then_separates_stopped_short_from_a_miss(self) -> None:
        stopped = self._run(
            slug="design-cellar",
            prompt=_cue("You kneel by the hatch. Do you open it?"),
            then=f"Yes. {REPLY_TRIGGER} {json.dumps('It opens.\n<!-- suggest:design-cellar -->')}",
        )
        run = stopped.runs[0]
        self.assertEqual(run.outcome("design-cellar"), "stopped-short")
        self.assertEqual((stopped.hits, stopped.hits_after), (0, 1))
        self.assertIn("It opens.", run.then_text or "")
        missed = self._run(
            slug="design-cellar",
            prompt=_cue("You walk on past the store."),
            then=f"I go on. {REPLY_TRIGGER} {json.dumps('The lane bends east.')}",
        )
        self.assertEqual(missed.runs[0].outcome("design-cellar"), "missed")
        self.assertEqual(missed.hits_after, 0)

    def test_no_follow_up_after_a_hit_or_without_then(self) -> None:
        hit = self._run(
            slug="design-cellar",
            prompt=_cue("Up.\n<!-- suggest:design-cellar -->"),
            then="Yes.",
        )
        self.assertIsNone(hit.runs[0].then_text)
        plain = self._run(slug="design-cellar", prompt=_cue("You wait."))
        self.assertIsNone(plain.runs[0].then_text)
        self.assertEqual(plain.runs[0].outcome("design-cellar"), "missed")

    def test_a_prompt_file_overrides_for_this_run_only(self) -> None:
        from lens.core.prompts import PromptStore, load_prompt_override_files

        override = self._dir / "held_back_b.txt"
        cue = json.dumps("From the override.\n<!-- suggest:design-cellar -->")
        override.write_text(f"B ARM {{triggers}} {REPLY_TRIGGER} {cue}\n")
        overrides = load_prompt_override_files(
            ["play.held_back=held_back_b.txt"], self._dir, self._dir
        )
        result = self._run(slug="design-cellar", prompt="I wait.", prompt_overrides=overrides)
        self.assertEqual(result.hits, 1)  # the override reached play's prompt
        self.assertIn("From the override.", result.runs[0].text)
        # Nothing shared changed: no project override, builtin text outside the run.
        self.assertFalse((self._dir / "prompts" / "prompts.toml").exists())
        self.assertNotIn("B ARM", PromptStore(self._dir).get("play.held_back"))

    def test_the_default_player_line_is_the_when(self) -> None:
        result = self._run(slug="design-cellar")
        self.assertEqual(result.player_line, "Elena opens the store cellar hatch")

    def test_a_trigger_play_would_not_see_is_refused_with_the_reason(self) -> None:
        (self._dir / "narrative" / "default" / "design-loft-tr.md").write_text("")
        try:
            with self.assertRaises(ValidationError) as caught:
                self._run(slug="design-loft")
            self.assertIn("not in play's [HELD BACK]", str(caught.exception))
            self.assertIn("listed: design-cellar", str(caught.exception))
        finally:
            (self._dir / "narrative" / "default" / "design-loft-tr.md").unlink()

    def test_cli_reports_a_rate(self) -> None:
        out = subprocess.run(
            [*_LENS, "test-play", "--trigger", "design-cellar", "-n", "2",
             "--prompt", _cue("You lift it.\n<!-- suggest:design-cellar -->")],
            cwd=self._dir, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("run 1: suggested design-cellar", out.stdout)
        self.assertIn("2/2 suggested design-cellar", out.stdout)
        prep_time = subprocess.run(
            [*_LENS, "test-play", "prep.hall", "--trigger", "design-hall-glow",
             "--at", "Day 7, before first light, at the hall door",
             "--prompt", _cue("<!-- suggest:design-hall-glow -->")],
            cwd=self._dir, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(prep_time.returncode, 0, prep_time.stderr)
        self.assertIn("with prep.hall+", prep_time.stdout)
        self.assertIn("scene: Day 7, before first light", prep_time.stdout)
        self.assertIn("1/1 suggested design-hall-glow", prep_time.stdout)
        bad = subprocess.run(
            [*_LENS, "test-play", "prep.store", "--at", "somewhere"],
            cwd=self._dir, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(bad.returncode, 1)
        self.assertIn("--at and --then only apply with --trigger", bad.stderr)

    def test_prep_time_ids_pin_the_scene_in_memory(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            self._run(slug="design-hall-glow")
        self.assertIn("lens test-play prep.hall --trigger design-hall-glow", str(caught.exception))
        result = self._run(
            slug="design-hall-glow",
            targets=["prep.hall"],
            prompt=_cue("A seam of light.\n<!-- suggest:design-hall-glow -->"),
        )
        self.assertEqual(result.hits, 1)
        self.assertEqual(result.targets, ["prep.hall"])

    def test_at_is_the_gms_last_passage_before_the_players_line(self) -> None:
        KnowledgeStore.clear_registry()
        session = ProjectSession(self._dir, self._dir)
        narrative = session.active_narrative
        assert narrative is not None
        plan = prepare_rehearsal(
            session=session,
            narrative=narrative,
            slug="design-cellar",
            prompt="I lift the hatch",
            at="Day 7, before first light, Elena kneels at the hatch",
        )
        scene_turns = [
            i for i, m in enumerate(plan.messages)
            if m["role"] == "assistant" and "Elena kneels at the hatch" in m["content"]
        ]
        self.assertEqual(len(scene_turns), 1, plan.messages)
        last = plan.messages[-1]
        self.assertEqual(last["role"], "user")
        self.assertIn("I lift the hatch", last["content"])
        self.assertLess(scene_turns[0], len(plan.messages) - 1)


if __name__ == "__main__":
    unittest.main()
