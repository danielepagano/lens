"""`test-play`: review prepared content as play would read it (issue #191).

The design session is driven through the fake LLM so its proposals are real
``[kb-op]`` blocks; the review itself goes through a recording stand-in for
``run_llm``, so each case can assert on the exact prompt the reviewer got and
hand back a review of a known shape.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from lens.core.commands.kb import kb_add
from lens.core.commands.pin import param_set, pin_add
from lens.core.exceptions import ValidationError
from lens.core.generation_artifacts import GenerationArtifacts, GenerationSegment
from lens.core.kb_pending import parse_kb_ops
from lens.core.knowledge import KnowledgeStore
from lens.core.llm_run import LlmRunRequest
from lens.core.narrative import NarrativeNode, find_unclosed_cursor_annotation
from lens.core.operators.design import DesignOperator
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.rpg.operators import test_play as tp
from lens.rpg.operators.test_play import (
    TestPlayOperator,
    extract_findings,
    is_design_session_node,
    story_node,
)
from lens.testing.fake_llm import KB_OP_TRIGGER, FakeLLMServer
from lens.testing.project import setup_test_project

PLAZA = """The Plaza Chase

- **Ground**: the plaza is a 30-ft square of stalls; half cover behind any stall.
- **Escape**: the thief escapes once 40 ft separate her from every PC.
"""

REVIEW = """## Cold read

The thief stands at the north stall; the party is at the fountain.

## Playthroughs

### 1. Rush

Round 1 the thief Dashes; the square is 30 ft, so the gap can never reach 40 ft.

## Findings

- **impossible** `encounter.plaza` — "40 ft separate her": the plaza is "a 30-ft
  square", so the escape condition cannot be met.
- **ambiguous** `encounter.plaza` — "half cover behind any stall": against whom.
"""

STORY_MARKER = "The pilgrims' square fills with lamplight at dusk."
DESIGN_TALK = "DESIGN-TALK: let's make the thief faster than everyone."


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _kb_add_trigger(kb_id: str, body: str) -> str:
    return f"{KB_OP_TRIGGER} " + json.dumps(
        {"tool": "kb_add", "arguments": {"id": kb_id, "body": body}}
    )


class _Recorder:
    """Stands in for ``run_llm``: records each request, returns *text*."""

    def __init__(self, text: str = REVIEW, *, interrupted: bool = False) -> None:
        self.text = text
        self.interrupted = interrupted
        self.requests: list[LlmRunRequest] = []

    async def __call__(self, request: LlmRunRequest) -> GenerationArtifacts:
        self.requests.append(request)
        return GenerationArtifacts(
            segments=[GenerationSegment(kind="prose", text=self.text)],
            interrupted=self.interrupted,
        )

    @property
    def prompt(self) -> str:
        messages = self.requests[-1].messages or []
        return "\n".join(str(m.get("content", "")) for m in messages)


class TestExtractFindings(unittest.TestCase):
    def test_typed_bullets_with_continuations(self) -> None:
        section, findings = extract_findings(REVIEW)
        assert section is not None
        self.assertTrue(section.startswith("- **impossible**"))
        self.assertEqual([f.kind for f in findings], ["impossible", "ambiguous"])
        self.assertIn('square", so the escape', findings[0].text)

    def test_section_ends_at_next_heading_of_same_level(self) -> None:
        section, findings = extract_findings(
            "## Findings\n\n- **gap** `x.y` — \"z\": w\n\n## Afterword\n\nnot a finding\n"
        )
        self.assertEqual(section, '- **gap** `x.y` — "z": w')
        self.assertEqual(len(findings), 1)

    def test_no_findings(self) -> None:
        section, findings = extract_findings("## Cold read\n\nx\n\n## Findings\n\nNo findings.\n")
        self.assertEqual(section, "No findings.")
        self.assertEqual(findings, [])

    def test_missing_section(self) -> None:
        self.assertEqual(extract_findings("just prose"), (None, []))

    def test_rules_error_kind(self) -> None:
        _, findings = extract_findings(
            "## Findings\n- **rules-error** `encounter.x` — \"2d6\": a 15-ft fall is 1d6.\n"
        )
        self.assertEqual([f.kind for f in findings], ["rules-error"])


class TestTestPlay(unittest.TestCase):
    _server: FakeLLMServer
    _orig_cwd: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._server = FakeLLMServer()
        cls._server.start()
        cls._orig_cwd = Path.cwd()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.stop()

    def setUp(self) -> None:
        self.project_dir = Path(tempfile.mkdtemp(prefix="lens_test_play_"))
        setup_test_project(
            self.project_dir, self._server.base_url, datasets=["rpg"], opening_write=False
        )
        os.chdir(self.project_dir)
        session = self._session()
        kb_add("pc.rowan", "Rowan, level 4 fighter. Speed 30 ft.", False)
        pin_add(session, "pc.rowan", None, [], None)
        root = self._narrative().md_path()
        root.write_text(root.read_text(encoding="utf-8") + f"\n{STORY_MARKER}\n", encoding="utf-8")
        Storage(self.project_dir).stage_all()

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        KnowledgeStore.clear_registry()
        shutil.rmtree(self.project_dir, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def _session(self) -> ProjectSession:
        KnowledgeStore.clear_registry()
        return ProjectSession(self.project_dir, self.project_dir)

    def _narrative(self) -> NarrativeNode:
        narrative = self._session().active_narrative
        assert narrative is not None
        return narrative

    def _open_design_with_proposal(self) -> NarrativeNode:
        session = self._session()
        _run(DesignOperator.run_design(
            session=session,
            narrative=self._narrative(),
            prompt=_kb_add_trigger("encounter.plaza", PLAZA),
            module_ids=None,
            pins=[],
            unpins=[],
            llm_id="mock",
            slug="plaza",
        ))
        cursor = self._narrative().find_cursor()
        md = cursor.md_path()
        md.write_text(md.read_text(encoding="utf-8") + f"\n{DESIGN_TALK}\n", encoding="utf-8")
        return cursor

    @contextmanager
    def _review(self, recorder: _Recorder) -> Generator[_Recorder]:
        with mock.patch.object(tp, "run_llm", recorder):
            yield recorder

    def _test_play(self, recorder: _Recorder, **kwargs: Any) -> tp.TestPlayResult:
        with self._review(recorder):
            return _run(TestPlayOperator.run_test_play(
                session=self._session(), narrative=self._narrative(), **kwargs
            ))

    def _git_status(self) -> str:
        import subprocess

        return subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.project_dir, capture_output=True, text=True, check=True,
        ).stdout

    # -- outside a session ----------------------------------------------

    def test_outside_a_session_an_id_is_required(self) -> None:
        with self.assertRaises(ValidationError):
            self._test_play(_Recorder())

    def test_outside_a_session_nothing_is_written(self) -> None:
        kb_add("encounter.plaza", PLAZA, False)
        Storage(self.project_dir).stage_all()
        before = self._git_status()
        result = self._test_play(_Recorder(), targets=["encounter.plaza"])

        self.assertIsNone(result.review_node)
        self.assertEqual([f.kind for f in result.findings], ["impossible", "ambiguous"])
        self.assertEqual(self._git_status(), before)

    def test_reads_plays_context(self) -> None:
        kb_add("encounter.plaza", PLAZA, False)
        recorder = _Recorder()
        self._test_play(recorder, targets=["encounter.plaza"])
        prompt = recorder.prompt

        self.assertIn("40 ft separate her", prompt)  # the target
        self.assertIn("KB['rules.rpg']", prompt)  # play's auto pins
        self.assertIn("KB['rules.system']", prompt)
        self.assertIn("Rowan, level 4 fighter", prompt)  # pc.* in scope
        self.assertIn(STORY_MARKER, prompt)  # the spine
        self.assertIn("## Findings", prompt)  # the review format
        self.assertTrue(recorder.requests[-1].enable_thinking)
        self.assertEqual(recorder.requests[-1].operator_name, "play")

    def test_unknown_id(self) -> None:
        with self.assertRaises(ValidationError):
            self._test_play(_Recorder(), targets=["encounter.nope"])

    def test_no_spine_drops_the_narrative_but_keeps_pcs(self) -> None:
        kb_add("encounter.plaza", PLAZA, False)
        recorder = _Recorder()
        self._test_play(recorder, targets=["encounter.plaza"], no_spine=True)

        self.assertNotIn(STORY_MARKER, recorder.prompt)
        self.assertIn("Rowan, level 4 fighter", recorder.prompt)
        self.assertIn("hypothetical", recorder.prompt)

    def test_prompt_states_circumstances_that_override_the_spine(self) -> None:
        kb_add("encounter.plaza", PLAZA, False)
        recorder = _Recorder()
        self._test_play(
            recorder, targets=["encounter.plaza"], prompt="night, two days after the siege"
        )

        self.assertIn("night, two days after the siege", recorder.prompt)
        self.assertIn("these win", recorder.prompt)

    def test_pinned_params_fill_what_the_caller_left_out(self) -> None:
        kb_add("encounter.plaza", PLAZA, False)
        session = self._session()
        param_set(session, "test_play", "targets", ["encounter.plaza"], None, None)
        param_set(session, "test_play", "prompt", ["dawn"], None, None)
        Storage(self.project_dir).stage_all()
        recorder = _Recorder()
        result = self._test_play(recorder)

        self.assertEqual(result.targets, ["encounter.plaza"])
        self.assertIn("ASSUMED CIRCUMSTANCES", recorder.prompt)
        self.assertIn("dawn", recorder.prompt)

    def test_test_play_profile_wins_when_configured(self) -> None:
        toml = self.project_dir / "lens.toml"
        toml.write_text(
            toml.read_text(encoding="utf-8") + '\n[operator.test_play]\nllm = "mock"\n',
            encoding="utf-8",
        )
        kb_add("encounter.plaza", PLAZA, False)
        recorder = _Recorder()
        self._test_play(recorder, targets=["encounter.plaza"])
        self.assertEqual(recorder.requests[-1].operator_name, "test_play")

    # -- inside a design session ----------------------------------------

    def test_default_targets_are_the_sessions_proposals(self) -> None:
        self._open_design_with_proposal()
        self.assertFalse((self.project_dir / "knowledge" / "encounter" / "plaza.md").exists())
        recorder = _Recorder()
        result = self._test_play(recorder)

        self.assertEqual(result.targets, ["encounter.plaza"])
        self.assertIn("40 ft separate her", recorder.prompt)

    def test_a_session_with_no_proposals_has_nothing_to_test(self) -> None:
        session = self._session()
        _run(DesignOperator.run_design(
            session=session, narrative=self._narrative(), prompt="just talking",
            module_ids=None, pins=[], unpins=[], llm_id="mock", slug="talk",
        ))
        with self.assertRaisesRegex(ValidationError, "nothing to test"):
            self._test_play(_Recorder())

    def test_story_excludes_the_design_sessions_own_text(self) -> None:
        design_node = self._open_design_with_proposal()
        self.assertTrue(is_design_session_node(design_node))
        self.assertEqual(story_node(design_node).key_path, ())
        recorder = _Recorder()
        self._test_play(recorder)

        self.assertIn(STORY_MARKER, recorder.prompt)
        self.assertNotIn("DESIGN-TALK", recorder.prompt)

    def test_review_lands_in_a_closed_child_and_findings_in_the_session(self) -> None:
        design_node = self._open_design_with_proposal()
        result = self._test_play(_Recorder(), prompt="market night")

        self.assertIsNotNone(result.review_node)
        narrative = self._narrative()
        # The cursor is back on the session node, with the session still open.
        cursor = narrative.find_cursor()
        self.assertEqual(cursor.key_path, design_node.key_path)
        self.assertTrue(is_design_session_node(cursor))

        child = design_node.child_node("test-play-plaza")
        child_text = child.md_path().read_text(encoding="utf-8")
        self.assertIn("## Playthroughs", child_text)
        self.assertIn("[test_play", child_text)
        self.assertIn("[/test_play]: #", child_text)

        session_text = design_node.md_path().read_text(encoding="utf-8")
        self.assertIn("[test_play:test-play-plaza]: #", session_text)
        self.assertIn("[/test_play:test-play-plaza]: #", session_text)
        self.assertIn("### Test-play findings: encounter.plaza", session_text)
        self.assertIn("> Assumed: market night", session_text)
        self.assertIn('> - **impossible** `encounter.plaza`', session_text)
        # Only the verdict reaches the session; the transcript stays in the child.
        self.assertNotIn("Playthroughs", session_text)
        self.assertIsNone(find_unclosed_cursor_annotation(
            session_text.split("[design", 1)[0]
        ))

    def test_proposals_survive_the_child_and_stay_proposals(self) -> None:
        self._open_design_with_proposal()
        self._test_play(_Recorder())

        session = self._session()
        self.assertIn("40 ft separate her", session.kb.get_objects(["encounter.plaza"])
                      ["encounter.plaza"].text)
        self.assertFalse((self.project_dir / "knowledge" / "encounter" / "plaza.md").exists())
        cursor_text = self._narrative().find_cursor().md_path().read_text(encoding="utf-8")
        self.assertEqual([op.id for op in parse_kb_ops(cursor_text)], ["encounter.plaza"])

    def test_the_next_design_turn_reads_the_findings(self) -> None:
        self._open_design_with_proposal()
        self._test_play(_Recorder())

        captured: list[str] = []
        from lens.core.operators import design as design_mod

        real = design_mod.run_llm

        async def _capture(request: LlmRunRequest) -> GenerationArtifacts:
            assert request.operator is not None and request.crawl_result is not None
            messages = request.operator.build_messages(
                request.crawl_result, request.params or {},
            )
            captured.append("\n".join(str(m.get("content", "")) for m in messages))
            return await real(request)

        with mock.patch.object(design_mod, "run_llm", _capture):
            _run(DesignOperator.run_design(
                session=self._session(), narrative=self._narrative(),
                prompt="address the findings", module_ids=None,
                pins=[], unpins=[], llm_id="mock",
            ))
        self.assertIn("Test-play findings: encounter.plaza", captured[0])
        self.assertIn("the plaza is \"a 30-ft", captured[0])
        self.assertNotIn("Round 1 the thief Dashes", captured[0])

    def test_runs_are_siblings(self) -> None:
        design_node = self._open_design_with_proposal()
        self._test_play(_Recorder())
        self._test_play(_Recorder())
        self.assertEqual(
            [k for k in design_node.child_keys() if k.startswith("test-play")],
            ["test-play-plaza", "test-play-plaza-1"],
        )

    def test_interrupted_review_writes_nothing(self) -> None:
        design_node = self._open_design_with_proposal()
        before = design_node.md_path().read_text(encoding="utf-8")
        result = self._test_play(_Recorder(interrupted=True))

        self.assertTrue(result.interrupted)
        self.assertIsNone(result.review_node)
        self.assertEqual(design_node.md_path().read_text(encoding="utf-8"), before)

    def test_a_review_without_findings_section_hands_on_the_whole_review(self) -> None:
        design_node = self._open_design_with_proposal()
        result = self._test_play(_Recorder("The plaza is too small."))

        self.assertIn("no Findings section", result.findings_text)
        self.assertIn("The plaza is too small.", design_node.md_path().read_text(encoding="utf-8"))

    def test_against_the_fake_llm_end_to_end(self) -> None:
        self._open_design_with_proposal()
        result = _run(TestPlayOperator.run_test_play(
            session=self._session(), narrative=self._narrative(), llm_id="mock",
        ))
        self.assertIsNotNone(result.review_node)
        self.assertTrue(is_design_session_node(self._narrative().find_cursor()))


if __name__ == "__main__":
    unittest.main()
