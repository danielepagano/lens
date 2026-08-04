"""Core workflow regression cases AW-02/AW-03 (skip remember, skip auto_compress)."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

from lens.core.knowledge import KnowledgeStore
from lens.core.media import MediaService
from lens.core.narrative import NarrativeNode
from lens.core.operators.section import SectionOperator
from lens.core.operators.write import WriteOperator
from lens.core.workflow_runner import WorkflowRunner
from lens.core.test.llm_run_mock import mock_run_llm
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.regression_fixtures import setup_auto_compress_low_threshold, setup_remember_section


class TestRegressionWorkflowAw02(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._fake = FakeLLMServer()
        self._fake.start()
        self._tmp = Path(tempfile.mkdtemp())
        setup_remember_section(self._tmp, self._fake.base_url)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def tearDown(self) -> None:
        self._fake.stop()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    async def test_aw02_skip_remember_keeps_kb_and_writes_summary(self) -> None:
        from lens.core.project import ProjectSession

        session = ProjectSession(self._tmp, self._tmp)
        narrative = session.active_narrative
        assert narrative is not None
        lore_before = (self._tmp / "knowledge" / "lore" / "testbench.md").read_text(
            encoding="utf-8"
        )

        async def _summary(*_a: object, **_k: object) -> str:
            return "Regression summary.\n"

        skip_remember_on_plan = False

        def _plan_has_remember(payload: dict[str, object]) -> bool:
            raw = payload.get("steps")
            if not isinstance(raw, list):
                return False
            for item in cast(list[object], raw):
                if isinstance(item, dict) and cast(dict[str, object], item).get("id") == "remember":
                    return True
            return False

        async def on_event(payload: dict[str, object]) -> None:
            nonlocal skip_remember_on_plan
            if (
                not skip_remember_on_plan
                and payload.get("type") == "workflow"
                and payload.get("action") == "plan"
                and _plan_has_remember(payload)
            ):
                workflow.signal_action("remember", "skip")
                skip_remember_on_plan = True

        workflow = WorkflowRunner(on_event=on_event)

        with patch("lens.core.operator.run_llm", mock_run_llm(_summary)):
            with patch(
                "lens.core.operators.session.apply_remember_patches",
                new_callable=AsyncMock,
            ) as mock_remember:
                await SectionOperator.run_end(
                    session=session,
                    narrative=narrative,
                    llm_id="mock",
                    workflow=workflow,
                )
                mock_remember.assert_not_called()

        lore_after = (self._tmp / "knowledge" / "lore" / "testbench.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(lore_after, lore_before)
        parent = NarrativeNode(narrative_root=narrative.narrative_root, key_path=())
        parent_text = parent.md_path().read_text(encoding="utf-8")
        self.assertIn("### Integration Summary", parent_text)
        self.assertIn("[/section:remember-smoke]", parent_text)


class TestRegressionWorkflowAw03(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._fake = FakeLLMServer()
        self._fake.start()
        self._tmp = Path(tempfile.mkdtemp())
        setup_auto_compress_low_threshold(self._tmp, self._fake.base_url)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def tearDown(self) -> None:
        self._fake.stop()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    async def test_aw03_skip_auto_compress_keeps_generation_only(self) -> None:
        from lens.core.project import ProjectSession

        session = ProjectSession(self._tmp, self._tmp)
        narrative = session.active_narrative
        assert narrative is not None
        skip_ac_on_plan = False

        def _plan_has_auto_compress(payload: dict[str, object]) -> bool:
            raw = payload.get("steps")
            if not isinstance(raw, list):
                return False
            for item in cast(list[object], raw):
                if (
                    isinstance(item, dict)
                    and cast(dict[str, object], item).get("id") == "auto_compress"
                ):
                    return True
            return False

        async def on_event(payload: dict[str, object]) -> None:
            nonlocal skip_ac_on_plan
            if (
                not skip_ac_on_plan
                and payload.get("type") == "workflow"
                and payload.get("action") == "plan"
                and _plan_has_auto_compress(payload)
            ):
                workflow.signal_action("auto_compress", "skip")
                skip_ac_on_plan = True

        workflow = WorkflowRunner(on_event=on_event)

        async def _text(*_a: object, **_k: object) -> str:
            return "Kept generation.\n"

        with patch("lens.core.operator.run_llm", mock_run_llm(_text)):
            with patch(
                "lens.core.auto_compress.run_compress",
                new_callable=AsyncMock,
            ) as mock_compress:
                await WriteOperator.run_inline(
                    session=session,
                    narrative=narrative,
                    prompt="go",
                    pins=[],
                    unpins=[],
                    llm_id="mock",
                    retry=False,
                    workflow=workflow,
                )
                mock_compress.assert_not_called()

        root = self._tmp / "narrative" / "story"
        children = [p for p in root.iterdir() if p.is_dir()]
        self.assertEqual(children, [])
        self.assertIn("Kept generation", (root / "_node.md").read_text(encoding="utf-8"))


class TestRegressionWorkflowAw04(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._fake = FakeLLMServer()
        self._fake.start()
        self._tmp = Path(tempfile.mkdtemp())
        setup_remember_section(self._tmp, self._fake.base_url)
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    def tearDown(self) -> None:
        self._fake.stop()
        KnowledgeStore.clear_registry()
        MediaService.clear_registry()

    async def test_aw04_cancel_mid_remember_rolls_back(self) -> None:
        from lens.core.project import ProjectSession

        session = ProjectSession(self._tmp, self._tmp)
        narrative = session.active_narrative
        assert narrative is not None
        lore_before = (self._tmp / "knowledge" / "lore" / "testbench.md").read_text(
            encoding="utf-8"
        )
        cancel = asyncio.Event()

        async def _summary(*_a: object, **_k: object) -> str:
            return "Would-be summary.\n"

        async def remember_then_cancel(*_a: object, **_k: object) -> str:
            cancel.set()
            return ""

        workflow = WorkflowRunner(session=session, cancel_event=cancel)

        with patch("lens.core.operator.run_llm", mock_run_llm(_summary)):
            with patch(
                "lens.core.operators.session.apply_remember_patches",
                new_callable=AsyncMock,
                side_effect=remember_then_cancel,
            ):
                await SectionOperator.run_end(
                    session=session,
                    narrative=narrative,
                    llm_id="mock",
                    workflow=workflow,
                    cancel_event=cancel,
                )

        lore_after = (self._tmp / "knowledge" / "lore" / "testbench.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(lore_after, lore_before)


class TestRegressionWorkflowAw05(unittest.IsolatedAsyncioTestCase):
    async def test_aw05_retryable_step_reruns_once(self) -> None:
        from lens.core.workflow_runner import StepResult, WorkflowStepDef

        events: list[dict[str, object]] = []
        attempts = 0

        async def on_event(payload: dict[str, object]) -> None:
            events.append(payload)

        workflow = WorkflowRunner(on_event=on_event)

        async def flaky() -> StepResult:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return StepResult(ok=False, error="transient")
            return StepResult(ok=True)

        async def signal_retry() -> None:
            await asyncio.sleep(0.05)
            workflow.signal_action("flaky", "retry")

        task = asyncio.create_task(signal_retry())
        outcome = await workflow.run([
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
        self.assertTrue(any(e.get("action") == "step_failed" for e in events))
