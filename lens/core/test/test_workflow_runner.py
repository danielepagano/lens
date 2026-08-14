"""Tests for WorkflowRunner scheduling."""

from __future__ import annotations

import asyncio
from typing import Any
import unittest

from lens.core.workflow_runner import (
    StepResult,
    WorkflowOutcome,
    WorkflowRunner,
    WorkflowStepDef,
    finalize_workflow_outcome,
    remember_result_is_failure,
    step_result_from_inline_outcome,
)


class TestWorkflowRunner(unittest.IsolatedAsyncioTestCase):
    async def test_run_emits_plan_and_completes_steps(self) -> None:
        events: list[dict[str, Any]] = []

        async def on_event(payload: dict[str, Any]) -> None:
            events.append(payload)

        runner = WorkflowRunner(on_event=on_event)

        async def ok_step() -> StepResult:
            return StepResult(ok=True)

        outcome = await runner.run([
            WorkflowStepDef(id="a", label="Step A", run=ok_step),
            WorkflowStepDef(id="b", label="Step B", run=ok_step),
        ])

        self.assertEqual(outcome.kind, "success")
        self.assertEqual([s.status for s in outcome.steps], ["success", "success"])
        self.assertEqual(events[0]["action"], "plan")
        self.assertTrue(
            any(e.get("action") == "step_start" and e.get("step_id") == "a" for e in events)
        )

    async def test_success_with_warnings_outcome_partial(self) -> None:
        async def soft_warn() -> StepResult:
            return StepResult(ok=True, warnings=("degraded slightly",))

        runner = WorkflowRunner()
        outcome = await runner.run(
            [
                WorkflowStepDef(id="w", label="W", run=soft_warn),
            ]
        )

        self.assertEqual(outcome.kind, "partial")
        self.assertEqual(outcome.steps[0].status, "success")
        self.assertEqual(outcome.steps[0].warnings, ("degraded slightly",))

    async def test_step_end_payload_includes_warnings(self) -> None:
        events: list[dict[str, Any]] = []

        async def on_event(payload: dict[str, Any]) -> None:
            events.append(payload)

        async def soft_warn() -> StepResult:
            return StepResult(ok=True, warnings=("a", "b"))

        runner = WorkflowRunner(on_event=on_event)
        await runner.run(
            [
                WorkflowStepDef(id="w", label="W", run=soft_warn),
            ]
        )

        ends = [e for e in events if e.get("action") == "step_end" and e.get("step_id") == "w"]
        self.assertTrue(ends)
        self.assertEqual(ends[-1].get("warnings"), ["a", "b"])

    async def test_cancel_skips_remaining_steps(self) -> None:
        cancel = asyncio.Event()
        runner = WorkflowRunner(cancel_event=cancel)

        async def step_one() -> StepResult:
            return StepResult(ok=True)

        async def step_two() -> StepResult:
            return StepResult(ok=True)

        cancel.set()
        outcome = await runner.run([
            WorkflowStepDef(id="one", label="One", run=step_one),
            WorkflowStepDef(id="two", label="Two", run=step_two),
        ])

        self.assertEqual(outcome.kind, "cancelled")
        self.assertEqual(outcome.steps[0].status, "skipped")
        self.assertEqual(outcome.steps[1].status, "skipped")

    async def test_retryable_failure_pause_retry(self) -> None:
        events: list[dict[str, Any]] = []
        attempts = 0

        async def on_event(payload: dict[str, Any]) -> None:
            events.append(payload)

        runner = WorkflowRunner(on_event=on_event)

        async def flaky() -> StepResult:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return StepResult(ok=False, error="boom")
            return StepResult(ok=True)

        async def signal_retry() -> None:
            await asyncio.sleep(0.05)
            runner.signal_action("flaky", "retry")

        task = asyncio.create_task(signal_retry())
        outcome = await runner.run([
            WorkflowStepDef(
                id="flaky",
                label="Flaky",
                run=flaky,
                failure_policy="retryable",
            ),
        ])
        await task

        self.assertEqual(attempts, 2)
        self.assertEqual(outcome.kind, "success")
        self.assertEqual(outcome.steps[0].status, "success")
        self.assertTrue(any(e.get("action") == "step_failed" for e in events))

    async def test_skip_after_failure(self) -> None:
        events: list[dict[str, Any]] = []

        async def on_event(payload: dict[str, Any]) -> None:
            events.append(payload)

        runner = WorkflowRunner(on_event=on_event)
        calls: list[str] = []

        async def fail() -> StepResult:
            return StepResult(ok=False, error="nope")

        async def after() -> StepResult:
            calls.append("after")
            return StepResult(ok=True)

        async def signal_skip() -> None:
            await asyncio.sleep(0.05)
            runner.signal_action("fail", "skip")

        task = asyncio.create_task(signal_skip())
        outcome = await runner.run([
            WorkflowStepDef(id="fail", label="Fail", run=fail, failure_policy="retryable"),
            WorkflowStepDef(id="after", label="After", run=after),
        ])
        await task

        self.assertEqual(outcome.steps[0].status, "skipped")
        self.assertEqual(calls, ["after"])
        self.assertEqual(outcome.kind, "success")


    async def test_non_interactive_retryable_fails_fast(self) -> None:
        runner = WorkflowRunner()

        async def fail() -> StepResult:
            return StepResult(ok=False, error="nope")

        outcome = await runner.run([
            WorkflowStepDef(id="fail", label="Fail", run=fail, failure_policy="retryable"),
        ])

        self.assertEqual(outcome.kind, "failed")
        self.assertEqual(outcome.steps[0].status, "failed")

    async def test_skip_planned_step_continues_to_close(self) -> None:
        calls: list[str] = []

        async def summarize() -> StepResult:
            await asyncio.sleep(0.05)
            return StepResult(ok=True)

        async def remember() -> StepResult:
            calls.append("remember")
            return StepResult(ok=True)

        async def close() -> StepResult:
            calls.append("close")
            return StepResult(ok=True)

        runner = WorkflowRunner()

        async def signal_skip() -> None:
            await asyncio.sleep(0.02)
            runner.signal_action("remember", "skip")

        task = asyncio.create_task(signal_skip())
        outcome = await runner.run([
            WorkflowStepDef(id="summarize", label="Summarize", run=summarize),
            WorkflowStepDef(
                id="remember",
                label="Remember",
                run=remember,
                skippable=True,
            ),
            WorkflowStepDef(id="close", label="Close", run=close),
        ])
        await task

        self.assertEqual(outcome.kind, "success")
        self.assertEqual(outcome.steps[1].status, "skipped")
        self.assertEqual(outcome.steps[2].status, "success")
        self.assertEqual(calls, ["close"])

    async def test_abort_rolls_back_pending(self) -> None:
        cancel = asyncio.Event()

        async def step_one() -> StepResult:
            return StepResult(ok=True)

        async def step_two() -> StepResult:
            cancel.set()
            return StepResult(ok=False, cancelled=True)

        runner = WorkflowRunner(cancel_event=cancel)
        outcome = await runner.run([
            WorkflowStepDef(id="one", label="One", run=step_one),
            WorkflowStepDef(
                id="two",
                label="Two",
                run=step_two,
                abort_rolls_back=True,
            ),
        ])

        self.assertTrue(outcome.rollback_pending)
        self.assertEqual(outcome.kind, "cancelled")
        self.assertEqual(outcome.steps[0].status, "success")
        self.assertEqual(outcome.steps[1].status, "cancelled")

    async def test_cancel_mid_step_preserves_prior_without_abort_rollback(self) -> None:
        import tempfile
        import subprocess
        from pathlib import Path

        from lens.core.project import ProjectSession
        from lens.core.storage import Storage

        tmp = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
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
        (tmp / "lens.toml").write_text('[project]\nnarrative = "n"\n')
        nd = tmp / "narrative" / "n"
        nd.mkdir(parents=True)
        (nd / "_node.md").write_text("# n\n")
        (tmp / "knowledge").mkdir()
        subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp,
            capture_output=True,
            check=True,
        )
        session = ProjectSession(tmp, tmp)
        cancel = asyncio.Event()
        marker = tmp / "step_one.txt"

        async def step_one() -> StepResult:
            Storage(tmp).write_file(marker, "done")
            return StepResult(ok=True)

        async def step_two() -> StepResult:
            cancel.set()
            return StepResult(ok=False, cancelled=True)

        runner = WorkflowRunner(session=session, cancel_event=cancel)
        outcome = await runner.run([
            WorkflowStepDef(id="one", label="One", run=step_one),
            WorkflowStepDef(id="two", label="Two", run=step_two),
        ])

        self.assertEqual(outcome.steps[0].status, "success")
        self.assertEqual(outcome.steps[1].status, "cancelled")
        self.assertEqual(outcome.kind, "partial")
        self.assertTrue(marker.exists())
        self.assertTrue(Storage(tmp).has_pending())


    async def test_step_scoped_cancel_skips_only_that_step(self) -> None:
        cancel = asyncio.Event()
        runner = WorkflowRunner(cancel_event=cancel)
        ran: list[str] = []

        async def refine() -> StepResult:
            runner.cancel_step("refine")
            interrupted = runner.step_cancel_event("refine").is_set()
            ran.append("refine")
            return StepResult(
                ok=True,
                warnings=("kept pre-refine text",) if interrupted else (),
            )

        async def persist() -> StepResult:
            ran.append("persist")
            return StepResult(ok=True)

        outcome = await runner.run([
            WorkflowStepDef(
                id="refine", label="Refining…", run=refine, cancel_scope="step"
            ),
            WorkflowStepDef(id="persist", label="Saving…", run=persist),
        ])

        self.assertEqual(ran, ["refine", "persist"])
        self.assertEqual(outcome.steps[0].status, "skipped")
        self.assertEqual(outcome.steps[0].warnings, ("kept pre-refine text",))
        self.assertEqual(outcome.steps[1].status, "success")
        self.assertFalse(outcome.interrupted)
        self.assertFalse(cancel.is_set())

    async def test_step_scoped_cancel_before_run_skips_the_step(self) -> None:
        runner = WorkflowRunner()
        ran: list[str] = []

        async def first() -> StepResult:
            runner.cancel_step("refine")
            ran.append("first")
            return StepResult(ok=True)

        async def refine() -> StepResult:
            ran.append("refine")
            return StepResult(ok=True)

        outcome = await runner.run([
            WorkflowStepDef(id="first", label="First", run=first),
            WorkflowStepDef(
                id="refine", label="Refining…", run=refine, cancel_scope="step"
            ),
        ])

        self.assertEqual(ran, ["first"])
        self.assertEqual(outcome.steps[1].status, "skipped")

    async def test_step_scoped_cancel_rejected_for_workflow_scoped_step(self) -> None:
        runner = WorkflowRunner()
        errors: list[str] = []

        async def step() -> StepResult:
            try:
                runner.cancel_step("plain")
            except ValueError as e:
                errors.append(str(e))
            return StepResult(ok=True)

        outcome = await runner.run([WorkflowStepDef(id="plain", label="P", run=step)])

        self.assertEqual(outcome.steps[0].status, "success")
        self.assertTrue(errors)
        self.assertIn("cannot be cancelled on its own", errors[0])

    async def test_step_cancel_event_also_fires_on_workflow_cancel(self) -> None:
        cancel = asyncio.Event()
        runner = WorkflowRunner(cancel_event=cancel)
        step_event = runner.step_cancel_event("refine")

        self.assertFalse(step_event.is_set())
        cancel.set()
        self.assertTrue(step_event.is_set())

    async def test_plan_carries_cancel_scope_and_rollback_flags(self) -> None:
        events: list[dict[str, Any]] = []

        async def on_event(payload: dict[str, Any]) -> None:
            events.append(payload)

        async def ok_step() -> StepResult:
            return StepResult(ok=True)

        runner = WorkflowRunner(on_event=on_event)
        await runner.run([
            WorkflowStepDef(
                id="refine", label="Refining…", run=ok_step, cancel_scope="step"
            ),
            WorkflowStepDef(
                id="compress", label="C", run=ok_step, abort_rolls_back=True
            ),
        ])

        plan = next(e for e in events if e.get("action") == "plan")
        by_id = {s["id"]: s for s in plan["steps"]}
        self.assertEqual(by_id["refine"].get("cancel_scope"), "step")
        self.assertNotIn("cancel_scope", by_id["compress"])
        self.assertTrue(by_id["compress"].get("abort_rolls_back"))
        self.assertNotIn("abort_rolls_back", by_id["refine"])

    async def test_plan_omits_steps_not_should_run_at_plan_time(self) -> None:
        events: list[dict[str, Any]] = []

        async def on_event(payload: dict[str, Any]) -> None:
            events.append(payload)

        async def step_one() -> StepResult:
            return StepResult(ok=True)

        async def step_two() -> StepResult:
            return StepResult(ok=True)

        runner = WorkflowRunner(on_event=on_event)
        await runner.run([
            WorkflowStepDef(id="one", label="One", run=step_one),
            WorkflowStepDef(
                id="two",
                label="Two",
                run=step_two,
                should_run=lambda: False,
            ),
        ])

        plan = next(e for e in events if e.get("action") == "plan")
        self.assertEqual([s["id"] for s in plan["steps"]], ["one"])

    async def test_should_run_re_evaluated_after_prior_step(self) -> None:
        gate = {"allow_second": False}

        async def step_one() -> StepResult:
            gate["allow_second"] = True
            return StepResult(ok=True)

        async def step_two() -> StepResult:
            return StepResult(ok=True)

        runner = WorkflowRunner()
        outcome = await runner.run([
            WorkflowStepDef(
                id="one",
                label="One",
                run=step_one,
                should_run=lambda: True,
            ),
            WorkflowStepDef(
                id="two",
                label="Two",
                run=step_two,
                should_run=lambda: gate["allow_second"],
            ),
        ])

        self.assertEqual(outcome.steps[0].status, "success")
        self.assertEqual(outcome.steps[1].status, "success")

    async def test_should_run_skips_when_false_at_execution(self) -> None:
        calls: list[str] = []

        async def step_one() -> StepResult:
            return StepResult(ok=True)

        async def step_two() -> StepResult:
            calls.append("ran")
            return StepResult(ok=True)

        runner = WorkflowRunner()
        outcome = await runner.run([
            WorkflowStepDef(id="one", label="One", run=step_one),
            WorkflowStepDef(
                id="two",
                label="Two",
                run=step_two,
                should_run=lambda: False,
            ),
        ])

        self.assertEqual(len(outcome.steps), 1)
        self.assertEqual(outcome.steps[0].id, "one")
        self.assertEqual(calls, [])

    async def test_non_interactive_retryable_skip(self) -> None:
        runner = WorkflowRunner()

        async def fail() -> StepResult:
            return StepResult(ok=False, error="nope")

        outcome = await runner.run([
            WorkflowStepDef(
                id="fail",
                label="Fail",
                run=fail,
                failure_policy="retryable",
                non_interactive_failure="skip",
            ),
        ])

        self.assertEqual(outcome.kind, "success")
        self.assertEqual(outcome.steps[0].status, "skipped")

    async def test_nested_run_preserves_outer_step_defs_for_skip(self) -> None:
        calls: list[str] = []

        async def inner_work() -> StepResult:
            await asyncio.sleep(0.05)
            return StepResult(ok=True)

        async def outer_with_nested_run() -> StepResult:
            await runner.run(
                [
                    WorkflowStepDef(id="inner", label="Inner", run=inner_work),
                ],
                emit_plan=False,
            )
            return StepResult(ok=True)

        async def tail() -> StepResult:
            calls.append("tail")
            return StepResult(ok=True)

        runner = WorkflowRunner()

        async def signal_skip() -> None:
            await asyncio.sleep(0.02)
            runner.signal_action("tail", "skip")

        task = asyncio.create_task(signal_skip())
        outcome = await runner.run([
            WorkflowStepDef(id="outer", label="Outer", run=outer_with_nested_run),
            WorkflowStepDef(id="tail", label="Tail", run=tail, skippable=True),
        ])
        await task

        self.assertEqual(outcome.steps[1].status, "skipped")
        self.assertEqual(calls, [])

    async def test_finalize_workflow_outcome_clears_rollback_pending(self) -> None:
        import tempfile
        import subprocess
        from pathlib import Path
        from unittest.mock import patch

        from lens.core.project import ProjectSession

        tmp = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
        (tmp / "lens.toml").write_text('[project]\nnarrative = "n"\n')
        (tmp / "narrative" / "n").mkdir(parents=True)
        (tmp / "narrative" / "n" / "_node.md").write_text("# n\n")
        (tmp / "knowledge").mkdir()
        session = ProjectSession(tmp, tmp)
        outcome = WorkflowOutcome(kind="cancelled", steps=[], rollback_pending=True)
        with patch("lens.core.commands.rollback.execute_rollback") as mock_rb:
            result = finalize_workflow_outcome(session, outcome)
            mock_rb.assert_called_once_with(session)
        self.assertFalse(result.rollback_pending)
        with patch("lens.core.commands.rollback.execute_rollback") as mock_rb:
            finalize_workflow_outcome(session, result)
            mock_rb.assert_not_called()


class TestWorkflowHelpers(unittest.TestCase):
    def test_remember_result_is_failure(self) -> None:
        self.assertTrue(remember_result_is_failure("\n\n<!-- remember: error: timeout -->\n"))
        self.assertFalse(remember_result_is_failure(""))

    def test_remember_failure_message(self) -> None:
        from lens.core.workflow_runner import remember_failure_message

        self.assertEqual(
            remember_failure_message("\n\n<!-- remember: error: timeout -->\n"),
            "remember failed",
        )

    def test_step_result_from_inline_outcome(self) -> None:
        self.assertTrue(step_result_from_inline_outcome("interrupted").cancelled)
        self.assertTrue(step_result_from_inline_outcome("ok").ok)
