"""Multiple independent modality refine passes, one workflow step each.

Passes are independent: no result feeds the next and nothing may depend on
running before or after another modality. What these tests do pin down is that
each pass gets its own skippable step, and that a spec is always built against
the text as it stands when that pass runs — see
:func:`lens.core.modalities.workflow.refine_spec_for_modality`.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from lens.core.generation_artifacts import GenerationArtifacts, GenerationSegment
from lens.core.modalities import (
    Modality,
    ModalityContext,
    RefinePassSpec,
    clear_registry_for_tests,
    ensure_modalities_registered,
    refine_step_id,
    register_modality,
    registered_refine_modality_ids,
    resolve_modalities,
)
from lens.core.modalities.types import PendingInlinePersist
from lens.core.modalities.workflow import (
    cache_refine_modality_ids_on_pending,
    resolve_refine_modality_ids,
)
from lens.core.operators.write import WriteOperator
from lens.core.pinning import set_modality_config
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.core.narrative import NarrativeNode
from lens.core.test.llm_run_mock import mock_run_llm
from lens.core.workflow_runner import WorkflowOutcome, WorkflowRunner

FIRST_ID = "refine_first"
SECOND_ID = "refine_second"
NO_REFINE_ID = "refine_none"


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True
    )
    return tmp


def _make_project(tmp: Path, slug: str = "test") -> tuple[Path, NarrativeNode]:
    (tmp / "lens.toml").write_text(f'[project]\nnarrative = "{slug}"\n')
    narrative_dir = tmp / "narrative" / slug
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text(f"# {slug}\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "project"], cwd=tmp, capture_output=True, check=True
    )
    return tmp, NarrativeNode(narrative_root=narrative_dir, key_path=())


class _TaggingRefineModality(Modality):
    """Appends ``<!-- <id> -->`` by way of its refine ``apply``."""

    id = "refine_tagging_base"

    def __init__(self) -> None:
        self.seen_text: list[str] = []
        self.spec_calls = 0
        self.declines_after: int | None = None

    def workflow_refine_pass(
        self, ctx: ModalityContext, text: str
    ) -> RefinePassSpec | None:
        del ctx
        self.spec_calls += 1
        self.seen_text.append(text)
        if self.declines_after is not None and self.spec_calls > self.declines_after:
            return None

        tag = f"<!-- {self.id} -->"

        def apply(_refined: str) -> str:
            return text.rstrip("\n") + f"\n{tag}\n"

        return RefinePassSpec(instruction=f"{self.id} instruction", apply=apply)


class _FirstRefineModality(_TaggingRefineModality):
    id = FIRST_ID


class _SecondRefineModality(_TaggingRefineModality):
    id = SECOND_ID


class _NoRefineModality(Modality):
    id = NO_REFINE_ID


_TAGGING_CLASSES: dict[str, type[_TaggingRefineModality]] = {
    FIRST_ID: _FirstRefineModality,
    SECOND_ID: _SecondRefineModality,
}


def _make_tagging(modality_id: str) -> _TaggingRefineModality:
    mod = _TAGGING_CLASSES[modality_id]()
    register_modality(mod)
    return mod


class _RegistryCleanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_for_tests()

    def tearDown(self) -> None:
        clear_registry_for_tests()
        ensure_modalities_registered()


class TestRefineCapableDiscovery(_RegistryCleanTestCase):
    def test_overriding_the_hook_is_enough_to_be_offered_a_step(self) -> None:
        """No separate opt-in flag, unlike ``contributes_workflow_post``."""
        mod = _make_tagging(FIRST_ID)
        self.assertTrue(mod.contributes_workflow_refine)
        self.assertIn(FIRST_ID, registered_refine_modality_ids())

    def test_modality_without_the_hook_is_not_offered_a_step(self) -> None:
        register_modality(_NoRefineModality())
        self.assertFalse(_NoRefineModality().contributes_workflow_refine)
        self.assertNotIn(NO_REFINE_ID, registered_refine_modality_ids())

    def test_registered_ids_are_ordered_deterministically(self) -> None:
        _make_tagging(SECOND_ID)
        _make_tagging(FIRST_ID)
        ids = registered_refine_modality_ids()
        self.assertEqual(list(ids), sorted(ids))


class TestResolveRefineIds(_RegistryCleanTestCase):
    def _ctx(self, root: Path, narrative: Any) -> ModalityContext:
        return ModalityContext(
            session=ProjectSession(root, root),
            narrative=narrative,
            focus_node=narrative,
            operator_name="write",
            crawl_result=None,
            params={},
            project_root=root,
        )

    def test_collects_every_contributing_modality_not_just_the_first(self) -> None:
        _make_tagging(FIRST_ID)
        _make_tagging(SECOND_ID)
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            storage = Storage(root)
            set_modality_config(narrative, FIRST_ID, "enabled", True, storage)
            set_modality_config(narrative, SECOND_ID, "enabled", True, storage)
            resolved, _ = resolve_modalities(WriteOperator, narrative)

            ids = resolve_refine_modality_ids(
                resolved, self._ctx(root, narrative), "body\n"
            )
            self.assertEqual(set(ids), {FIRST_ID, SECOND_ID})

    def test_declining_modality_is_excluded(self) -> None:
        first = _make_tagging(FIRST_ID)
        first.declines_after = 0  # returns None from the very first call
        _make_tagging(SECOND_ID)
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            storage = Storage(root)
            set_modality_config(narrative, FIRST_ID, "enabled", True, storage)
            set_modality_config(narrative, SECOND_ID, "enabled", True, storage)
            resolved, _ = resolve_modalities(WriteOperator, narrative)

            ids = resolve_refine_modality_ids(
                resolved, self._ctx(root, narrative), "body\n"
            )
            self.assertEqual(ids, (SECOND_ID,))

    def test_cache_records_ids_once(self) -> None:
        mod = _make_tagging(FIRST_ID)
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality_config(narrative, FIRST_ID, "enabled", True, Storage(root))
            resolved, _ = resolve_modalities(WriteOperator, narrative)
            pending = PendingInlinePersist(
                mode="start",
                cursor=narrative,
                tag="",
                artifacts=GenerationArtifacts(
                    segments=[GenerationSegment("prose", "line\n")]
                ),
                verbatim_prefix="",
                existing_ann=None,
                owner=narrative.to_address(),
                narrative=narrative,
                operator_name="write",
            )
            mod.spec_calls = 0
            ctx = self._ctx(root, narrative)
            cache_refine_modality_ids_on_pending(pending, resolved, ctx)
            cache_refine_modality_ids_on_pending(pending, resolved, ctx)
            self.assertEqual(mod.spec_calls, 1)
            self.assertEqual(pending.refine_modality_ids, (FIRST_ID,))


class _InlineRefineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_for_tests()

    def tearDown(self) -> None:
        clear_registry_for_tests()
        ensure_modalities_registered()

    def _run_write(
        self,
        root: Path,
        narrative: Any,
        *,
        workflow: WorkflowRunner | None = None,
        refine: Any = None,
    ) -> WorkflowOutcome | None:
        async def _draft(*_a: object, **_k: object) -> str:
            return "Draft.\n"

        async def _fake_refine(*_a: object, **_k: object) -> GenerationArtifacts:
            # Content is irrelevant: each spec's ``apply`` ignores it and rewrites
            # from the text it captured, which is what these tests are about.
            return GenerationArtifacts(
                segments=[GenerationSegment("prose", "refined\n")]
            )

        outcome: WorkflowOutcome | None = None

        async def _run() -> None:
            nonlocal outcome
            with patch("lens.core.operator.run_llm", mock_run_llm(_draft)):
                with patch(
                    "lens.core.modalities.workflow.run_refine_pass",
                    side_effect=refine or _fake_refine,
                ):
                    with contextlib.redirect_stdout(io.StringIO()):
                        with contextlib.redirect_stderr(io.StringIO()):
                            outcome = await WriteOperator.run_inline(
                                session=ProjectSession(root, root),
                                narrative=narrative,
                                prompt="go",
                                pins=[],
                                unpins=[],
                                llm_id="mock",
                                retry=False,
                                workflow=workflow,
                            )

        asyncio.run(_run())
        return outcome


class TestTwoPassesRunIndependently(_InlineRefineTestCase):
    def test_both_passes_apply_and_each_gets_its_own_step(self) -> None:
        _make_tagging(FIRST_ID)
        _make_tagging(SECOND_ID)
        planned: set[str] = set()

        async def on_event(payload: dict[str, object]) -> None:
            if payload.get("action") != "plan":
                return
            steps = payload.get("steps")
            if not isinstance(steps, list):
                return
            for raw in cast(list[object], steps):
                if isinstance(raw, dict):
                    step_id = cast(dict[str, object], raw).get("id")
                    if isinstance(step_id, str):
                        planned.add(step_id)

        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            storage = Storage(root)
            set_modality_config(narrative, FIRST_ID, "enabled", True, storage)
            set_modality_config(narrative, SECOND_ID, "enabled", True, storage)

            self._run_write(root, narrative, workflow=WorkflowRunner(on_event=on_event))

            self.assertIn(refine_step_id(FIRST_ID), planned)
            self.assertIn(refine_step_id(SECOND_ID), planned)
            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertIn(f"<!-- {FIRST_ID} -->", text)
            self.assertIn(f"<!-- {SECOND_ID} -->", text)

    def test_whichever_pass_runs_last_sees_the_other_edit(self) -> None:
        """Specs are rebuilt per step, so no pass captures stale text.

        Deliberately order-agnostic: the framework promises only that each spec is
        built against the current text, never which modality goes first.
        """
        first = _make_tagging(FIRST_ID)
        second = _make_tagging(SECOND_ID)

        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            storage = Storage(root)
            set_modality_config(narrative, FIRST_ID, "enabled", True, storage)
            set_modality_config(narrative, SECOND_ID, "enabled", True, storage)

            self._run_write(root, narrative, workflow=WorkflowRunner())

            self.assertTrue(first.seen_text)
            self.assertTrue(second.seen_text)
            # Exactly one of them ran last, and that one must have observed the
            # other's tag when its spec was rebuilt.
            first_saw_second = f"<!-- {SECOND_ID} -->" in first.seen_text[-1]
            second_saw_first = f"<!-- {FIRST_ID} -->" in second.seen_text[-1]
            self.assertTrue(
                first_saw_second or second_saw_first,
                "neither pass observed the other's edit — specs are being cached",
            )

    def test_skipping_one_pass_leaves_the_other_running(self) -> None:
        _make_tagging(FIRST_ID)
        _make_tagging(SECOND_ID)
        skipped = False

        async def on_event(payload: dict[str, object]) -> None:
            nonlocal skipped
            if skipped or payload.get("action") != "plan":
                return
            steps = payload.get("steps")
            if not isinstance(steps, list):
                return
            target = refine_step_id(FIRST_ID)
            for raw in cast(list[object], steps):
                if isinstance(raw, dict) and cast(dict[str, object], raw).get("id") == target:
                    runner.signal_action(target, "skip")
                    skipped = True
                    return

        runner = WorkflowRunner(on_event=on_event)
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            storage = Storage(root)
            set_modality_config(narrative, FIRST_ID, "enabled", True, storage)
            set_modality_config(narrative, SECOND_ID, "enabled", True, storage)

            self._run_write(root, narrative, workflow=runner)

            self.assertTrue(skipped)
            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertNotIn(f"<!-- {FIRST_ID} -->", text)
            self.assertIn(f"<!-- {SECOND_ID} -->", text)

    def test_pass_declining_at_execution_time_is_skipped_not_failed(self) -> None:
        """A modality may want a pass at plan time and decline once its step runs."""
        first = _make_tagging(FIRST_ID)
        # 1 call at plan time, then decline when the step rebuilds the spec.
        first.declines_after = 1
        _make_tagging(SECOND_ID)

        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            storage = Storage(root)
            set_modality_config(narrative, FIRST_ID, "enabled", True, storage)
            set_modality_config(narrative, SECOND_ID, "enabled", True, storage)

            self._run_write(root, narrative, workflow=WorkflowRunner())

            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertNotIn(f"<!-- {FIRST_ID} -->", text)
            self.assertIn(f"<!-- {SECOND_ID} -->", text)
            self.assertIn("Draft.", text)

    def test_cancelling_a_pass_keeps_the_draft_and_finishes_the_workflow(self) -> None:
        """Cancel on a refine step drops that pass only — not the generation.

        The step's LLM call gets the runner's *step* cancel event, so an interrupted
        pass falls back to the pre-refine text and persist still runs.
        """
        _make_tagging(FIRST_ID)
        _make_tagging(SECOND_ID)
        runner = WorkflowRunner()
        target = refine_step_id(FIRST_ID)

        async def _refine(*_a: object, **kwargs: object) -> GenerationArtifacts:
            cancel_event = kwargs.get("cancel_event")
            if isinstance(cancel_event, asyncio.Event) and not cancel_event.is_set():
                # Only the first pass is cancelled; stand in for the user clicking it.
                with contextlib.suppress(ValueError):
                    runner.cancel_step(target)
                if cancel_event.is_set():
                    return GenerationArtifacts(interrupted=True)
            return GenerationArtifacts(
                segments=[GenerationSegment("prose", "refined\n")]
            )

        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            storage = Storage(root)
            set_modality_config(narrative, FIRST_ID, "enabled", True, storage)
            set_modality_config(narrative, SECOND_ID, "enabled", True, storage)

            outcome = self._run_write(
                root, narrative, workflow=runner, refine=_refine
            )

            assert outcome is not None
            self.assertFalse(outcome.interrupted)
            statuses = {s.id: s.status for s in outcome.steps}
            self.assertEqual(statuses[target], "skipped")
            self.assertEqual(statuses["persist"], "success")

            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertIn("Draft.", text)
            self.assertNotIn(f"<!-- {FIRST_ID} -->", text)
            self.assertIn(f"<!-- {SECOND_ID} -->", text)

    def test_single_pass_still_works_without_a_runner(self) -> None:
        _make_tagging(FIRST_ID)
        with tempfile.TemporaryDirectory() as tmp:
            root, narrative = _make_project(_init_repo(Path(tmp)))
            set_modality_config(narrative, FIRST_ID, "enabled", True, Storage(root))

            self._run_write(root, narrative)

            text = narrative.md_path().read_text(encoding="utf-8")
            self.assertIn(f"<!-- {FIRST_ID} -->", text)


if __name__ == "__main__":
    unittest.main()
