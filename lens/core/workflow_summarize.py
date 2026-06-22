"""Shared workflow steps for summarize → remember → close patterns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from lens.core.context import CrawlResult, CrawlSpec, crawl
from lens.core.knowledge import KnowledgeStore
from lens.core.narrative import NarrativeNode
from lens.core.exceptions import OperatorError
from lens.core.operators.session import apply_remember_patches, generate_summary_block
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.core.workflow_runner import (
    StepResult,
    WorkflowStepDef,
    remember_failure_message,
    remember_result_is_failure,
)


@dataclass
class SummarizeRememberState:
    slug: str
    summary: str = ""
    remember_suffix: str = ""
    crawl_result: CrawlResult | None = None
    content: str = ""


def remember_should_run(crawl_result: CrawlResult | None, project_root: Any) -> bool:
    if crawl_result is None or not crawl_result.pinned_ids:
        return False
    store = KnowledgeStore.for_project(project_root)
    pinned_objects = store.get_objects(crawl_result.pinned_ids)
    return any(
        any(t.startswith("remember.") for t in obj.tags)
        for obj in pinned_objects.values()
    )


def build_summarize_remember_steps(
    state: SummarizeRememberState,
    *,
    session: ProjectSession,
    cursor: NarrativeNode,
    operator_name: str,
    llm_id: str | None,
    reasoning: str | None,
    on_token: Callable[[str], Awaitable[None]] | None,
    cancel_event: Any | None,
    storage: Storage | None,
    system_key: str,
    instruction_key: str,
    summary_guidance: str | None = None,
    summarize_should_run: Callable[[], bool] | None = None,
    prepare_crawl: Callable[[], CrawlResult] | None = None,
    summarize_empty: bool = False,
    operator: type[Any] | None = None,
    operator_params: dict[str, Any] | None = None,
    narrative: NarrativeNode | None = None,
) -> list[WorkflowStepDef]:
    """Build summarize and remember workflow steps sharing *state*."""

    def _crawl() -> CrawlResult:
        if prepare_crawl is not None:
            return prepare_crawl()
        spec = CrawlSpec.of(cursor, storage=storage)
        if operator is not None:
            spec = spec.with_operator(
                operator,
                operator_params or {},
                session=session,
                narrative=narrative or cursor,
            )
        return crawl(spec)

    async def run_summarize() -> StepResult:
        if not state.content and not summarize_empty:
            return StepResult(ok=True, skipped=True)
        crawl_result = _crawl()
        state.crawl_result = crawl_result
        try:
            state.summary = await generate_summary_block(
                slug=state.slug,
                crawl_result=crawl_result,
                content=state.content,
                project_root=session.project_root,
                operator_name=operator_name,
                llm_id=llm_id,
                on_token=on_token,
                cancel_event=cancel_event,
                reasoning=reasoning,
                system_key=system_key,
                instruction_key=instruction_key,
                summary_guidance=summary_guidance,
            )
        except OperatorError as exc:
            return StepResult(ok=False, error=str(exc))
        return StepResult(ok=True)

    async def run_remember() -> StepResult:
        if state.crawl_result is None or not state.content:
            return StepResult(ok=True, skipped=True)
        suffix = await apply_remember_patches(
            crawl_result=state.crawl_result,
            content=state.content,
            project_root=session.project_root,
            llm_id=llm_id,
            reasoning=reasoning,
            cancel_event=cancel_event,
            storage=storage,
        )
        if cancel_event is not None and cancel_event.is_set():
            return StepResult(ok=False, cancelled=True)
        if remember_result_is_failure(suffix):
            state.remember_suffix = suffix
            return StepResult(ok=False, error=remember_failure_message(suffix))
        state.remember_suffix = suffix
        return StepResult(ok=True)

    def summarize_run() -> bool:
        if summarize_should_run is not None:
            return summarize_should_run()
        return bool(state.content) or summarize_empty

    def remember_run() -> bool:
        crawl_result = state.crawl_result if state.crawl_result is not None else _crawl()
        return remember_should_run(crawl_result, session.project_root)

    return [
        WorkflowStepDef(
            id="summarize",
            label="Summarizing…",
            run=run_summarize,
            should_run=summarize_run,
            failure_policy="fatal",
        ),
        WorkflowStepDef(
            id="remember",
            label="Updating memory…",
            run=run_remember,
            should_run=remember_run,
            failure_policy="retryable",
            non_interactive_failure="skip",
            skippable=True,
            abort_rolls_back=True,
        ),
    ]
