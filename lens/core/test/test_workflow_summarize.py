"""Tests for summarize → remember workflow step planning."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from lens.core.context import CrawlResult
from lens.core.knowledge import KnowledgeStore
from lens.core.project import ProjectSession
from lens.core.workflow_runner import StepResult, WorkflowRunner, WorkflowStepDef
from lens.core.workflow_summarize import (
    SummarizeRememberState,
    build_summarize_remember_steps,
    remember_should_run,
)


class TestRememberShouldRun(unittest.TestCase):
    def test_false_without_pins(self) -> None:
        crawl = MagicMock(spec=CrawlResult)
        crawl.pinned_ids = []
        self.assertFalse(remember_should_run(crawl, Path("/tmp")))

    def test_false_when_no_remember_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge" / "person").mkdir(parents=True)
            (root / "knowledge" / "person" / "amy.md").write_text("Amy\n", encoding="utf-8")
            (root / "knowledge" / "tags.toml").write_text(
                '[tags]\nperson.amy = ["fiction"]\n', encoding="utf-8"
            )
            crawl = MagicMock(spec=CrawlResult)
            crawl.pinned_ids = ["person.amy"]
            self.assertFalse(remember_should_run(crawl, root))


class TestRememberStepPlan(unittest.TestCase):
    def test_remember_omitted_from_plan_without_remember_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge" / "person").mkdir(parents=True)
            (root / "knowledge" / "person" / "amy.md").write_text("Amy\n", encoding="utf-8")
            (root / "knowledge" / "tags.toml").write_text(
                '[tags]\nperson.amy = ["fiction"]\n', encoding="utf-8"
            )
            session = ProjectSession(git_root=root, project_root=root)
            crawl = MagicMock(spec=CrawlResult)
            crawl.pinned_ids = ["person.amy"]
            state = SummarizeRememberState(slug="ch", content="section prose here")
            steps = build_summarize_remember_steps(
                state,
                session=session,
                cursor=MagicMock(),
                operator_name="section",
                llm_id=None,
                reasoning=None,
                on_token=None,
                cancel_event=None,
                storage=None,
                system_key="session.summary_system",
                instruction_key="session.summary_instruction_template",
                prepare_crawl=lambda: crawl,
                summarize_empty=True,
            )
            remember = next(s for s in steps if s.id == "remember")
            self.assertFalse(remember.should_run())


def _project_with_remember_target(root: Path) -> ProjectSession:
    """A project whose pinned ``person.amy`` is a remember target."""
    (root / "knowledge" / "person").mkdir(parents=True)
    (root / "knowledge" / "person" / "amy.md").write_text("Amy\n", encoding="utf-8")
    # `[tags]` maps tag → objects; the remember target is the *object*.
    (root / "knowledge" / "tags.toml").write_text(
        '[tags]\n"remember.core" = ["person.amy"]\n', encoding="utf-8"
    )
    KnowledgeStore.clear_registry()
    return ProjectSession(git_root=root, project_root=root)


class TestSkipMemoryMidRun(unittest.TestCase):
    """Stopping ``remember`` yourself drops the memory pass, not the session end."""

    def _run(
        self,
        root: Path,
        remember_impl: Any,
        *,
        cancel_event: asyncio.Event | None = None,
        runner: WorkflowRunner | None = None,
    ) -> tuple[Any, SummarizeRememberState, list[str]]:
        session = _project_with_remember_target(root)
        crawl = MagicMock(spec=CrawlResult)
        crawl.pinned_ids = ["person.amy"]
        state = SummarizeRememberState(slug="ch", content="session prose here")
        ran: list[str] = []

        async def run_close() -> StepResult:
            ran.append("close")
            return StepResult(ok=True)

        async def fake_summary(**_kwargs: object) -> str:
            return "<!-- summary -->\nWhat happened.\n"

        runner = runner or WorkflowRunner(cancel_event=cancel_event)
        steps = build_summarize_remember_steps(
            state,
            session=session,
            cursor=MagicMock(),
            operator_name="chat",
            llm_id=None,
            reasoning=None,
            on_token=None,
            cancel_event=cancel_event,
            storage=None,
            system_key="session.summary_system",
            instruction_key="session.summary_instruction_template",
            prepare_crawl=lambda: crawl,
            summarize_empty=True,
            workflow=runner,
        )
        steps.append(
            WorkflowStepDef(id="close", label="Closing session…", run=run_close)
        )

        async def go() -> Any:
            with patch(
                "lens.core.workflow_summarize.generate_summary_block",
                side_effect=fake_summary,
            ):
                with patch(
                    "lens.core.workflow_summarize.apply_remember_patches",
                    side_effect=remember_impl,
                ):
                    return await runner.run(steps)

        return asyncio.run(go()), state, ran

    def test_skip_keeps_summary_and_still_closes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = WorkflowRunner()

            async def remember_impl(**kwargs: object) -> str:
                # The user presses "Skip memory" while the pass is running.
                runner.cancel_step("remember")
                step_event = kwargs.get("cancel_event")
                assert isinstance(step_event, asyncio.Event)
                assert step_event.is_set(), "the pass must listen on the step's event"
                return ""

            outcome, state, ran = self._run(root, remember_impl, runner=runner)

            self.assertIn("close", ran)
            self.assertIn("What happened.", state.summary)
            statuses = {s.id: s.status for s in outcome.steps}
            self.assertEqual(statuses["remember"], "skipped")
            self.assertEqual(statuses["close"], "success")
            self.assertFalse(outcome.interrupted)
            remember_snap = next(s for s in outcome.steps if s.id == "remember")
            self.assertTrue(
                any("summary kept" in w for w in remember_snap.warnings),
                remember_snap.warnings,
            )

    def test_skip_reports_objects_already_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            runner = WorkflowRunner()

            async def remember_impl(**kwargs: object) -> str:
                applied = cast("list[str]", kwargs.get("applied_out"))
                assert isinstance(applied, list)
                applied.append("person.amy")  # a patch landed before the click
                runner.cancel_step("remember")
                return ""

            outcome, _state, ran = self._run(root, remember_impl, runner=runner)

            self.assertIn("close", ran)
            remember_snap = next(s for s in outcome.steps if s.id == "remember")
            self.assertTrue(
                any("person.amy" in w for w in remember_snap.warnings),
                remember_snap.warnings,
            )

    def test_stream_cancel_still_stops_before_close(self) -> None:
        """The stream-wide stop is unchanged: it ends the workflow, not just a step."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cancel = asyncio.Event()

            async def remember_impl(**_kwargs: object) -> str:
                cancel.set()
                return ""

            outcome, _state, ran = self._run(root, remember_impl, cancel_event=cancel)

            self.assertNotIn("close", ran)
            statuses = {s.id: s.status for s in outcome.steps}
            self.assertEqual(statuses["remember"], "cancelled")
            self.assertTrue(outcome.interrupted)

    def test_plan_tells_the_ui_what_the_button_means(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = _project_with_remember_target(root)
            crawl = MagicMock(spec=CrawlResult)
            crawl.pinned_ids = ["person.amy"]
            events: list[dict[str, Any]] = []

            async def on_event(payload: dict[str, Any]) -> None:
                events.append(payload)

            async def fake_summary(**_kwargs: object) -> str:
                return "summary\n"

            async def remember_impl(**_kwargs: object) -> str:
                return ""

            runner = WorkflowRunner(on_event=on_event)
            steps = build_summarize_remember_steps(
                SummarizeRememberState(slug="ch", content="prose"),
                session=session,
                cursor=MagicMock(),
                operator_name="chat",
                llm_id=None,
                reasoning=None,
                on_token=None,
                cancel_event=None,
                storage=None,
                system_key="session.summary_system",
                instruction_key="session.summary_instruction_template",
                prepare_crawl=lambda: crawl,
                summarize_empty=True,
                workflow=runner,
            )

            async def go() -> None:
                with patch(
                    "lens.core.workflow_summarize.generate_summary_block",
                    side_effect=fake_summary,
                ):
                    with patch(
                        "lens.core.workflow_summarize.apply_remember_patches",
                        side_effect=remember_impl,
                    ):
                        await runner.run(steps)

            asyncio.run(go())

            plan = next(e for e in events if e.get("action") == "plan")
            remember = next(s for s in plan["steps"] if s["id"] == "remember")
            self.assertEqual(remember.get("cancel_scope"), "step")
            self.assertEqual(remember.get("cancel_label"), "Skip memory")
            self.assertNotIn("abort_rolls_back", remember)
