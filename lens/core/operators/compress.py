"""Manual and automated compress: LLM picks a line range (text_select) and delegates to collate."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from lens.core.commands.pin import resolve_node
from lens.core.compression import (
    Aggressiveness,
    build_auto_directive,
    get_visible_text,
    measure_visible_bytes,
)
from lens.core.pinning import set_last_compress_size
from lens.core.exceptions import OperatorError, LensException, ValidationError
from lens.core.llm import LLMError, ToolCall
from lens.core.llm_run import LlmRunRequest, run_llm_final
from lens.core.operator_params import apply_pinned_invocation
from lens.core.narrative import NarrativeNode
from lens.core.operators.collate import CollateOperator
from lens.core.project import ProjectSession, validate_slug
from lens.core.storage import Storage
from lens.core.workflow_runner import (
    StepResult,
    WorkflowOutcome,
    WorkflowRunner,
    WorkflowStepDef,
    finalize_workflow_outcome,
)
from lens.core.prompts import PromptStore
from lens.core.text_select import (
    Selection,
    SelectionError,
    resolve_storage_selection_to_disk_inclusive_lines_via_llm_view,
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompressNoCollate:
    """Model finished without ``compress_collate``; narrative files unchanged."""

    explanation: str


COMPRESS_COLLATE_TOOL_NAME: Final = "compress_collate"

_LINE_SELECTOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "'target' must be the exact full text of one logical line from the file (no trailing "
        "newline on that line), or the sentinels '@@@start' / '@@@end' for document edges. "
        "Do not pass a substring or partial line as 'target'. Omit 'before' and 'after' when "
        "that line is unique. If the same full line appears more than once, supply 'before' "
        "and/or 'after' as full adjacent lines only (verbatim complete lines, never fragments)."
    ),
    "properties": {
        "target": {"type": "string"},
        "before": {"type": "array", "items": {"type": "string"}},
        "after": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["target"],
}

COMPRESS_COLLATE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": COMPRESS_COLLATE_TOOL_NAME,
        "description": (
            "Move a contiguous range of lines from the cursor node into a new child section "
            "(collate). Only call when the user request matches a clear span of prose in the "
            "document and the range respects existing section summary blocks (see instructions). "
            "If nothing fits, do not call this tool — explain in plain text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": (
                        "Slug for the new child section (letters, digits, underscores, hyphens only)."
                    ),
                },
                "selection": {
                    "type": "object",
                    "description": (
                        "Inclusive line range: 'start' and optional 'end' selectors. "
                        "Omit 'end' to select exactly one line."
                    ),
                    "properties": {
                        "start": _LINE_SELECTOR_SCHEMA,
                        "end": _LINE_SELECTOR_SCHEMA,
                    },
                    "required": ["start"],
                },
            },
            "required": ["id", "selection"],
        },
    },
}


def compress_arguments_to_line_range(
    node_text: str, arguments: dict[str, Any]
) -> tuple[str, int, int]:
    """Parse ``compress_collate`` tool arguments into slug and 1-based inclusive line numbers."""
    raw_id = arguments.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ValueError("compress_collate: 'id' must be a non-empty string")
    slug = raw_id.strip()
    if not validate_slug(slug):
        raise ValueError(
            f"compress_collate: invalid section id {slug!r} (alphanumeric, underscores, hyphens only)"
        )
    sel_raw = arguments.get("selection")
    if not isinstance(sel_raw, dict):
        raise ValueError("compress_collate: 'selection' must be an object")
    selection = Selection.from_dict(sel_raw)
    start_line, end_line = resolve_storage_selection_to_disk_inclusive_lines_via_llm_view(
        node_text, selection
    )
    return slug, start_line, end_line


def _pick_compress_tool_call(tool_calls: list[ToolCall]) -> ToolCall | None:
    for tc in tool_calls:
        if tc.name == COMPRESS_COLLATE_TOOL_NAME:
            return tc
    return None


def _no_tool_message(final_text: str) -> str:
    body = final_text.strip()
    head = (
        "The model did not call compress_collate, so nothing was collated. "
        "If the passage you want is unclear, try naming it more specifically or "
        "use structure-collate with explicit line numbers."
    )
    if body:
        return f"{head}\n\n---\n\n{body}"
    return head


async def run_compress(
    *,
    session: ProjectSession,
    narrative: NarrativeNode,
    prompt: str | None = None,
    aggressiveness: Aggressiveness | None = None,
    address: str | None = None,
    pins: list[str] | None = None,
    unpins: list[str] | None = None,
    llm_id: str | None = None,
    reasoning: str | None = None,
    summary_guide: str | None = None,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
    no_tool_call_ok: bool = False,
    workflow: WorkflowRunner | None = None,
    on_status: Callable[[str], None] | None = None,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> Storage | CompressNoCollate | WorkflowOutcome:
    """One LLM round with ``compress_collate`` tool, then :class:`CollateOperator` on success.

    Supply exactly one of:

    - A non-empty *prompt* — tells the model what prose span to collate (manual prompts).
    - *aggressiveness* — automated directives (low / medium / high); used when there is
      no user prompt (CLI/UI manual ``--aggressiveness``, or internal auto-compress).

    Returns the :class:`~lens.core.storage.Storage` used for collate (and any follow-up
    writes that must stay in the same pending transaction), :class:`CompressNoCollate`
    when *no_tool_call_ok* is true and the model omitted the tool, or
    :class:`~lens.core.workflow_runner.WorkflowOutcome` when the workflow was interrupted
    or aborted (rollback already applied via :func:`finalize_workflow_outcome`).
    """
    stripped_prompt = prompt.strip() if prompt else ""
    has_prompt = bool(stripped_prompt)
    has_aggr = aggressiveness is not None
    if has_prompt and has_aggr:
        raise ValidationError("compress: pass a prompt or aggressiveness, not both")
    if not has_prompt and not has_aggr:
        raise ValidationError(
            "compress: provide a non-empty prompt or aggressiveness (low | medium | high)"
        )

    node_arg = address.strip() if address and address.strip() else None
    try:
        target = resolve_node(session, node_arg)
    except (LensException, ValueError, RuntimeError) as e:
        raise ValidationError(f"compress: {e}") from e
    llm_id, reasoning, _ = apply_pinned_invocation(
        slug="compress",
        project_root=session.project_root,
        focus_node=target,
        narrative=None,
        llm_id=llm_id,
        reasoning=reasoning,
        extra_params=None,
    )
    address_str = str(target.to_address())
    node_text = target.md_path().read_text(encoding="utf-8")
    llm_view = session.new_storage().normalize_raw_text(
        node_text, source_id=f"compress:{address_str}"
    ).llm_view

    store = PromptStore(session.project_root)

    if has_prompt:
        system = store.get("compress.system")
        user = store.format(
            "compress.instruction_template",
            prompt=stripped_prompt,
            node_body=llm_view.visible_for_llm,
        )
    else:
        from lens.core.compression import CompressConfig  # noqa: PLC0415 — avoid circular at module level

        assert aggressiveness is not None
        config = CompressConfig.from_project(session.project_root)
        directive = build_auto_directive(store, aggressiveness, config)
        system = store.get("compress.auto_system")
        user = store.format(
            "compress.auto_instruction_template",
            directive=directive,
            node_body=llm_view.visible_for_llm,
            sm=config.sm,
            m=config.m,
            l=config.lg,
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    select_state: dict[str, Any] = {
        "slug": None,
        "start_line": None,
        "end_line": None,
        "no_collate": None,
        "storage": None,
    }

    async def run_compress_select() -> StepResult:
        try:
            final = await run_llm_final(
                LlmRunRequest(
                    project_root=session.project_root,
                    messages=messages,
                    llm_id=llm_id,
                    tools=[COMPRESS_COLLATE_TOOL],
                    command_tool_handlers=None,
                    cancel_event=cancel_event,
                    on_token=on_token,
                    reasoning=reasoning,
                    operator_name="compress",
                ),
            )
        except LLMError as e:
            return StepResult(ok=False, error=f"compress: LLM stream ended without a completion: {e}")

        if final.interrupted or (cancel_event is not None and cancel_event.is_set()):
            return StepResult(ok=False, cancelled=True)

        tc = _pick_compress_tool_call(final.tool_calls)
        if tc is None:
            if no_tool_call_ok:
                body = (final.text or "").strip()
                select_state["no_collate"] = CompressNoCollate(
                    explanation=body or "(model sent no tool call and no text)"
                )
                return StepResult(ok=True)
            return StepResult(ok=False, error=_no_tool_message(final.text))

        _log.info(
            "compress_collate tool call address=%s tool_call_id=%s\n%s",
            address_str,
            tc.id,
            json.dumps(tc.arguments, indent=2, ensure_ascii=False, default=str),
        )

        try:
            slug, start_line, end_line = compress_arguments_to_line_range(
                node_text, tc.arguments
            )
        except (SelectionError, ValueError, TypeError) as e:
            return StepResult(ok=False, error=f"compress_collate: {e}")

        select_state["slug"] = slug
        select_state["start_line"] = start_line
        select_state["end_line"] = end_line
        return StepResult(ok=True)

    async def run_collate_step() -> StepResult:
        if select_state["no_collate"] is not None:
            return StepResult(ok=True, skipped=True)
        slug = select_state["slug"]
        if slug is None:
            return StepResult(ok=False, cancelled=True)
        try:
            collate_storage = await CollateOperator.run_collate(
                session=session,
                narrative=narrative,
                id=slug,
                address_str=address_str,
                start_line=select_state["start_line"],
                end_line=select_state["end_line"],
                pins=pins or [],
                unpins=unpins or [],
                llm_id=llm_id,
                reasoning=reasoning,
                on_token=on_token,
                cancel_event=cancel_event,
                summary_guidance=summary_guide.strip() if summary_guide and summary_guide.strip() else None,
                workflow=runner,
                on_status=on_status,
            )
        except OperatorError as e:
            if str(e) == "collate aborted":
                return StepResult(ok=False, cancelled=True)
            return StepResult(ok=False, error=str(e))
        select_state["storage"] = collate_storage
        try:
            new_text = target.md_path().read_text(encoding="utf-8")
            new_size = measure_visible_bytes(get_visible_text(new_text))
            set_last_compress_size(target, new_size, collate_storage)
        except Exception:
            _log.debug("compress: failed to record last_size in front matter", exc_info=True)
        return StepResult(ok=True)

    def collate_should_run() -> bool:
        return select_state["no_collate"] is None

    runner = workflow or WorkflowRunner(
        session=session,
        cancel_event=cancel_event,
        on_status=on_status,
        on_event=on_event,
    )
    outcome = await runner.run(
        [
            WorkflowStepDef(
                id="compress_select",
                label="Selecting range…",
                run=run_compress_select,
                failure_policy="fatal",
            ),
            WorkflowStepDef(
                id="compress_collate",
                label="Collating…",
                run=run_collate_step,
                should_run=collate_should_run,
                failure_policy="retryable",
                abort_rolls_back=True,
            ),
        ],
        emit_plan=workflow is None,
    )
    finalize_workflow_outcome(session, outcome)
    if outcome.interrupted or outcome.kind == "cancelled" or outcome.rollback_pending:
        return outcome
    if select_state["no_collate"] is not None:
        return select_state["no_collate"]
    return select_state["storage"]
