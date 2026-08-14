"""Thin scheduler for multi-step operator workflows (generate → hooks, summarize → remember)."""

from __future__ import annotations

import asyncio
import contextvars
import logging
import sys
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from lens.core.project import ProjectSession

_log = logging.getLogger(__name__)

WorkflowEventHandler = Callable[[dict[str, Any]], Awaitable[None]]
WorkflowStepStatus = Literal[
    "planned", "running", "success", "skipped", "failed", "cancelled"
]
WorkflowOutcomeKind = Literal["success", "partial", "failed", "cancelled"]
WorkflowAction = Literal["retry", "skip"]
FailurePolicy = Literal["fatal", "retryable", "warn"]
NonInteractiveFailure = Literal["fail", "skip"]
CancelScope = Literal["workflow", "step"]

_workflow_step_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "lens_workflow_step_id",
    default=None,
)


def current_workflow_step_id() -> str | None:
    return _workflow_step_id.get()


@asynccontextmanager
async def workflow_step_scope(step_id: str | None):
    if step_id is None:
        yield
        return
    token = _workflow_step_id.set(step_id)
    try:
        yield
    finally:
        _workflow_step_id.reset(token)


@dataclass
class StepResult:
    ok: bool
    error: str | None = None
    warnings: tuple[str, ...] = ()
    skipped: bool = False
    cancelled: bool = False


class StepCancelEvent(asyncio.Event):
    """Cancel event for one step, also fired by the workflow-wide cancel.

    Only ``is_set()`` is consulted by the LLM loop, so the union is computed
    there rather than mirrored with a watcher task; ``wait()`` still tracks this
    event alone.
    """

    def __init__(self, workflow_cancel: asyncio.Event | None) -> None:
        super().__init__()
        self._workflow_cancel = workflow_cancel

    def is_set(self) -> bool:
        if self._workflow_cancel is not None and self._workflow_cancel.is_set():
            return True
        return super().is_set()


@dataclass
class WorkflowStepSnapshot:
    id: str
    label: str
    status: WorkflowStepStatus
    error: str | None = None
    warnings: tuple[str, ...] = ()
    skippable: bool = False
    cancel_scope: CancelScope = "workflow"
    abort_rolls_back: bool = False
    cancel_label: str | None = None


@dataclass
class WorkflowOutcome:
    kind: WorkflowOutcomeKind
    steps: list[WorkflowStepSnapshot]
    interrupted: bool = False
    rollback_pending: bool = False


@dataclass
class WorkflowStepDef:
    id: str
    label: str
    run: Callable[[], Awaitable[StepResult]]
    should_run: Callable[[], bool] = lambda: True
    failure_policy: FailurePolicy = "fatal"
    non_interactive_failure: NonInteractiveFailure = "fail"
    skippable: bool = False
    """User may skip this step from the plan preview before it runs (forward-only)."""
    abort_rolls_back: bool = False
    """Abort while this step is running discards the whole operator pending transaction."""
    cancel_scope: CancelScope = "workflow"
    """``"step"``: cancelling mid-run stops only this step; the workflow keeps going
    with whatever the earlier steps produced (refine passes, which are pure
    improvements over an already-good result)."""
    cancel_label: str | None = None
    """Button text for the mid-run cancel, when the generic wording is too vague
    about what survives (e.g. ``"Skip memory"`` on ``remember``)."""


class WorkflowRunner:
    """Run named steps with plan preview, forward skip, retry-on-failure, and abort."""

    def __init__(
        self,
        *,
        session: Any = None,
        cancel_event: asyncio.Event | None = None,
        on_event: WorkflowEventHandler | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        del session
        self._cancel_event = cancel_event
        self._on_event = on_event
        self._on_status = on_status
        self._action_event = asyncio.Event()
        self._pending_action: WorkflowAction | None = None
        self._paused_step_id: str | None = None
        self._skip_requested: set[str] = set()
        self._step_cancelled: set[str] = set()
        self._step_cancel_events: dict[str, StepCancelEvent] = {}
        self._snapshots: list[WorkflowStepSnapshot] = []
        self._step_defs: dict[str, WorkflowStepDef] = {}
        self._steps_list: list[WorkflowStepDef] = []
        self._pending_inline: Any = None
        self._resolved_modalities: Any = None
        self._modality_context: Any = None

    def set_inline_modality_state(
        self,
        *,
        pending: Any = None,
        resolved: Any = None,
        modality_context: Any = None,
    ) -> None:
        if pending is not None:
            self._pending_inline = pending
        if resolved is not None:
            self._resolved_modalities = resolved
        if modality_context is not None:
            self._modality_context = modality_context

    def clear_inline_modality_state(self) -> None:
        self._pending_inline = None
        self._resolved_modalities = None
        self._modality_context = None

    @property
    def pending_inline(self) -> Any:
        return self._pending_inline

    @property
    def resolved_modalities(self) -> Any:
        return self._resolved_modalities

    @property
    def modality_context(self) -> Any:
        return self._modality_context

    @property
    def paused_step_id(self) -> str | None:
        return self._paused_step_id

    @property
    def on_event_handler(self) -> WorkflowEventHandler | None:
        return self._on_event

    def step_cancel_event(self, step_id: str) -> asyncio.Event:
        """Cancel event scoped to *step_id* (also fires on the workflow-wide cancel).

        Steps that declare ``cancel_scope="step"`` pass this — not the workflow
        event — to their LLM calls, so cancelling one does not abort the rest.
        """
        ev = self._step_cancel_events.get(step_id)
        if ev is None:
            ev = StepCancelEvent(self._cancel_event)
            self._step_cancel_events[step_id] = ev
        return ev

    def cancel_step(self, step_id: str) -> None:
        """Stop *step_id* alone; the workflow continues with what it already has."""
        step_def = self._step_defs.get(step_id)
        if step_def is None:
            raise ValueError(f"unknown workflow step {step_id!r}")
        if step_def.cancel_scope != "step":
            raise ValueError(
                f"workflow step {step_id!r} cannot be cancelled on its own"
            )
        snap = self._snap_for(step_id)
        status = snap.status if snap is not None else None
        if status == "planned":
            self._skip_requested.add(step_id)
            return
        if status != "running":
            raise ValueError(
                f"workflow step {step_id!r} is not running (status={status!r})"
            )
        self._step_cancelled.add(step_id)
        self.step_cancel_event(step_id).set()

    def _cancelled_alone(self, step_id: str) -> bool:
        """The step was cancelled on its own, with no workflow-wide cancel behind it."""
        return step_id in self._step_cancelled and not self._is_cancelled()

    def signal_action(self, step_id: str, action: WorkflowAction) -> None:
        step_def = self._step_defs.get(step_id)
        if step_def is None:
            raise ValueError(f"unknown workflow step {step_id!r}")
        if action == "skip":
            snap = self._snap_for(step_id)
            if snap is not None and snap.status == "planned" and step_def.skippable:
                self._skip_requested.add(step_id)
                return
            if self._paused_step_id == step_id:
                self._pending_action = action
                self._action_event.set()
                return
            raise ValueError(
                f"workflow step {step_id!r} is not skippable now "
                f"(status={snap.status if snap else 'unknown'!r}, paused={self._paused_step_id!r})"
            )
        if self._paused_step_id != step_id:
            raise ValueError(
                f"workflow not paused on step {step_id!r} (paused={self._paused_step_id!r})"
            )
        self._pending_action = action
        self._action_event.set()

    async def run(
        self,
        steps: list[WorkflowStepDef],
        *,
        emit_plan: bool = True,
    ) -> WorkflowOutcome:
        self._steps_list = steps
        for step_def in steps:
            self._step_defs[step_def.id] = step_def
        plan_steps: list[WorkflowStepSnapshot] = []
        for step_def in steps:
            if not step_def.should_run():
                continue
            plan_steps.append(self._plan_snapshot(step_def))
        if emit_plan:
            self._snapshots = list(plan_steps)
            await self._emit(
                {"type": "workflow", "action": "plan", "steps": self._snapshot_dicts()}
            )
        else:
            self._snapshots.extend(plan_steps)
            await self._emit(
                {"type": "workflow", "action": "plan", "steps": self._snapshot_dicts()}
            )

        rollback_pending = False
        aborted = False

        for step_def in steps:
            if not step_def.should_run():
                continue

            snap = self._snap_for(step_def.id)
            if snap is None:
                snap = self._plan_snapshot(step_def)
                self._snapshots.append(snap)
                await self._emit(
                    {"type": "workflow", "action": "plan", "steps": self._snapshot_dicts()}
                )

            if snap.status in ("skipped", "cancelled", "success", "failed"):
                continue

            if step_def.id in self._skip_requested:
                snap.status = "skipped"
                await self._emit_step_end(step_def.id, "skipped")
                continue

            if aborted:
                self._mark_remaining_cancelled_from(step_def.id)
                break

            if self._is_cancelled():
                if snap.status == "planned":
                    snap.status = "skipped"
                    await self._emit_step_end(step_def.id, "skipped")
                    self._mark_remaining_skipped_from(step_def.id)
                else:
                    self._mark_remaining_cancelled_from(step_def.id)
                aborted = True
                break

            snap.status = "running"
            await self._emit_step_start(step_def)

            result = await self._run_step_with_policy(step_def)

            if self._cancelled_alone(step_def.id):
                snap.status = "skipped"
                snap.warnings = result.warnings
                await self._emit_step_end(step_def.id, "skipped")
                continue

            if result.cancelled or self._is_cancelled():
                snap.status = "cancelled"
                if step_def.abort_rolls_back:
                    rollback_pending = True
                    self._mark_remaining_skipped_from(step_def.id)
                else:
                    self._mark_remaining_cancelled_from(step_def.id)
                aborted = True
                break

            if result.skipped:
                snap.status = "skipped"
                await self._emit_step_end(step_def.id, "skipped")
                continue

            if not result.ok:
                if step_def.failure_policy == "retryable":
                    if self._on_event is None:
                        if step_def.non_interactive_failure == "skip":
                            snap.status = "skipped"
                            snap.error = result.error
                            await self._emit_step_end(step_def.id, "skipped")
                            continue
                        snap.status = "failed"
                        snap.error = result.error
                        await self._emit_step_failed(
                            step_def.id, result.error or "failed", retryable=False
                        )
                        await self._emit_step_end(step_def.id, "failed")
                        self._mark_remaining_cancelled_from(step_def.id)
                        break
                    snap.status = "failed"
                    snap.error = result.error
                    self._paused_step_id = step_def.id
                    await self._emit_step_failed(
                        step_def.id,
                        result.error or "failed",
                        retryable=True,
                    )
                    action = await self._wait_for_action(step_def.id)
                    self._paused_step_id = None
                    if action == "retry":
                        snap.status = "running"
                        await self._emit_step_start(step_def)
                        result = await self._run_step_with_policy(step_def)
                        if self._cancelled_alone(step_def.id):
                            snap.status = "skipped"
                            snap.warnings = result.warnings
                            await self._emit_step_end(step_def.id, "skipped")
                            continue
                        if result.cancelled or self._is_cancelled():
                            snap.status = "cancelled"
                            if step_def.abort_rolls_back:
                                rollback_pending = True
                                self._mark_remaining_skipped_from(step_def.id)
                            else:
                                self._mark_remaining_cancelled_from(step_def.id)
                            aborted = True
                            break
                        if result.skipped:
                            snap.status = "skipped"
                            await self._emit_step_end(step_def.id, "skipped")
                            continue
                        if not result.ok:
                            snap.status = "failed"
                            snap.error = result.error
                            await self._emit_step_end(step_def.id, "failed")
                            self._mark_remaining_cancelled_from(step_def.id)
                            break
                    elif action == "skip":
                        snap.status = "skipped"
                        snap.error = result.error
                        await self._emit_step_end(step_def.id, "skipped")
                        continue
                    else:
                        snap.status = "cancelled"
                        if step_def.abort_rolls_back:
                            rollback_pending = True
                            self._mark_remaining_skipped_from(step_def.id)
                        else:
                            self._mark_remaining_cancelled_from(step_def.id)
                        aborted = True
                        break
                elif step_def.failure_policy == "warn":
                    snap.status = "success"
                    snap.error = None
                    snap.warnings = (result.error,) if result.error else ()
                    await self._emit_step_end(step_def.id, "success")
                    continue
                else:
                    snap.status = "failed"
                    snap.error = result.error
                    await self._emit_step_failed(
                        step_def.id, result.error or "failed", retryable=False
                    )
                    await self._emit_step_end(step_def.id, "failed")
                    self._mark_remaining_cancelled_from(step_def.id)
                    break

            snap.status = "success"
            snap.error = None
            snap.warnings = result.warnings
            await self._emit_step_end(step_def.id, "success")

        kind = self._outcome_kind(aborted, rollback_pending)
        return WorkflowOutcome(
            kind=kind,
            steps=list(self._snapshots),
            interrupted=self._is_cancelled() or aborted,
            rollback_pending=rollback_pending,
        )

    def _plan_snapshot(self, step_def: WorkflowStepDef) -> WorkflowStepSnapshot:
        return WorkflowStepSnapshot(
            step_def.id,
            step_def.label,
            "planned",
            skippable=step_def.skippable,
            cancel_scope=step_def.cancel_scope,
            abort_rolls_back=step_def.abort_rolls_back,
            cancel_label=step_def.cancel_label,
        )

    def _snap_for(self, step_id: str) -> WorkflowStepSnapshot | None:
        for snap in self._snapshots:
            if snap.id == step_id:
                return snap
        return None

    def _mark_remaining_skipped_from(self, after_step_id: str) -> None:
        seen = False
        for step_def in self._steps_list:
            if step_def.id == after_step_id:
                seen = True
                continue
            if not seen:
                continue
            snap = self._snap_for(step_def.id)
            if snap is not None and snap.status == "planned":
                snap.status = "skipped"

    def _mark_remaining_cancelled_from(self, after_step_id: str) -> None:
        seen = False
        for step_def in self._steps_list:
            if step_def.id == after_step_id:
                seen = True
                continue
            if not seen:
                continue
            snap = self._snap_for(step_def.id)
            if snap is not None and snap.status in ("planned", "running"):
                snap.status = "cancelled"

    async def _run_step_with_policy(self, step_def: WorkflowStepDef) -> StepResult:
        try:
            async with workflow_step_scope(step_def.id):
                return await step_def.run()
        except Exception as exc:
            _log.exception("workflow step %s failed", step_def.id)
            if step_def.failure_policy == "warn":
                return StepResult(ok=False, error=str(exc))
            return StepResult(ok=False, error=str(exc))

    def _is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    async def _wait_for_action(self, step_id: str) -> WorkflowAction | Literal["cancel"]:
        self._paused_step_id = step_id
        self._pending_action = None
        self._action_event.clear()
        while True:
            if self._is_cancelled():
                return "cancel"
            if self._pending_action is not None:
                return self._pending_action
            try:
                await asyncio.wait_for(self._action_event.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                continue

    def _outcome_kind(
        self, aborted: bool, rollback_pending: bool
    ) -> WorkflowOutcomeKind:
        if rollback_pending:
            return "cancelled"
        if aborted:
            if any(s.status == "success" for s in self._snapshots):
                return "partial"
            return "cancelled"
        if any(s.status == "failed" for s in self._snapshots):
            return "failed"
        if any(s.warnings for s in self._snapshots):
            return "partial"
        return "success"

    def _snapshot_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "id": s.id,
                "label": s.label,
                "status": s.status,
                **({"error": s.error} if s.error else {}),
                **({"warnings": list(s.warnings)} if s.warnings else {}),
                **({"skippable": True} if s.skippable else {}),
                **({"cancel_scope": s.cancel_scope} if s.cancel_scope != "workflow" else {}),
                **({"abort_rolls_back": True} if s.abort_rolls_back else {}),
                **({"cancel_label": s.cancel_label} if s.cancel_label else {}),
            }
            for s in self._snapshots
        ]

    async def _emit(self, payload: dict[str, Any]) -> None:
        if self._on_event is not None:
            await self._on_event(payload)
        elif self._on_status is not None and payload.get("type") == "workflow":
            action = payload.get("action")
            if action == "step_start":
                self._on_status(f"{payload.get('label', payload.get('step_id'))}…")
            elif action == "step_failed":
                self._on_status(
                    f"{payload.get('step_id')} failed: {payload.get('error', '')}"
                )
        else:
            action = payload.get("action")
            if payload.get("type") == "workflow" and action in (
                "step_start",
                "step_failed",
            ):
                print(
                    f"workflow: {payload.get('step_id')}: {action}",
                    file=sys.stderr,
                )

    async def _emit_step_start(self, step_def: WorkflowStepDef) -> None:
        await self._emit(
            {
                "type": "workflow",
                "action": "step_start",
                "step_id": step_def.id,
                "label": step_def.label,
            }
        )

    async def _emit_step_end(self, step_id: str, status: WorkflowStepStatus) -> None:
        snap = self._snap_for(step_id)
        payload: dict[str, Any] = {
            "type": "workflow",
            "action": "step_end",
            "step_id": step_id,
            "status": status,
        }
        if snap is not None and snap.warnings:
            payload["warnings"] = list(snap.warnings)
        await self._emit(payload)

    async def _emit_step_failed(
        self, step_id: str, error: str, *, retryable: bool
    ) -> None:
        await self._emit(
            {
                "type": "workflow",
                "action": "step_failed",
                "step_id": step_id,
                "error": error,
                "retryable": retryable,
            }
        )


def remember_result_is_failure(suffix: str) -> bool:
    return "<!-- remember: error:" in suffix


def step_result_from_inline_outcome(
    outcome: Literal["ok", "interrupted"],
) -> StepResult:
    if outcome == "interrupted":
        return StepResult(ok=False, cancelled=True)
    return StepResult(ok=True)


def finalize_workflow_outcome(
    session: ProjectSession,
    outcome: WorkflowOutcome,
) -> WorkflowOutcome:
    """Roll back when ``rollback_pending``; raise :class:`~lens.core.operator.OperatorError` on failed steps."""
    if outcome.rollback_pending:
        from lens.core.commands.rollback import execute_rollback

        execute_rollback(session)
        outcome.rollback_pending = False
    if outcome.kind == "failed":
        from lens.core.exceptions import OperatorError

        failed = next(s for s in outcome.steps if s.status == "failed")
        raise OperatorError(failed.error or f"workflow step {failed.id} failed")
    return outcome


def remember_failure_message(suffix: str) -> str:
    if "<!-- remember: error:" in suffix:
        return "remember failed"
    return suffix.strip() or "remember failed"
