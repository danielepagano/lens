"""Manual and automated compress: LLM picks a line range (text_select) and delegates to collate."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

from lens.core.commands.pin import resolve_node
from lens.core.compression import (
    Aggressiveness,
    build_auto_directive,
    get_visible_text,
    measure_visible_bytes,
)
from lens.core.pinning import set_last_compress_size
from lens.core.exceptions import LensException
from lens.core.llm import ToolCall, collect_final_payload, generate_stream
from lens.core.operator import OperatorError
from lens.core.narrative import NarrativeNode
from lens.core.operators.collate import CollateOperator
from lens.core.project import ProjectSession, validate_slug
from lens.core.storage import Storage
from lens.core.prompts import PromptStore
from lens.core.text_select import (
    Selection,
    SelectionError,
    resolve_storage_selection_to_disk_inclusive_lines,
    storage_text_llm_view,
)

_log = logging.getLogger(__name__)

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
    start_line, end_line = resolve_storage_selection_to_disk_inclusive_lines(
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
) -> Storage | None:
    """One LLM round with ``compress_collate`` tool, then :class:`CollateOperator` on success.

    Either *prompt* (manual path) or *aggressiveness* (auto path) must be provided.

    Returns the :class:`~lens.core.storage.Storage` used for collate (and any follow-up
    writes that must stay in the same pending transaction), or ``None`` when the LLM
    stream was interrupted before collate ran.
    """
    if prompt is None and aggressiveness is None:
        raise OperatorError("compress: prompt is required when aggressiveness is not set")

    node_arg = address.strip() if address and address.strip() else None
    try:
        target = resolve_node(session, node_arg)
    except (LensException, ValueError, RuntimeError) as e:
        raise OperatorError(f"compress: {e}") from e
    address_str = str(target.to_address())
    node_text = target.md_path().read_text(encoding="utf-8")
    llm_view = storage_text_llm_view(node_text)

    store = PromptStore(session.project_root)

    if prompt is not None:
        stripped = prompt.strip()
        if not stripped:
            raise OperatorError("compress: prompt is required")
        system = store.get("compress.system")
        user = store.format(
            "compress.instruction_template",
            prompt=stripped,
            node_body=llm_view.visible_for_llm,
        )
    else:
        from lens.core.compression import CompressConfig  # noqa: PLC0415 — avoid circular at module level

        config = CompressConfig.from_project(session.project_root)
        directive = build_auto_directive(store, aggressiveness, config)  # type: ignore[arg-type]
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

    final = await collect_final_payload(
        generate_stream(
            messages,
            session.project_root,
            llm_id=llm_id,
            tools=[COMPRESS_COLLATE_TOOL],
            cancel_event=cancel_event,
            command_tool_handlers=None,
            reasoning=reasoning,
            operator_name="compress",
        ),
        on_preview=on_token,
    )
    if final is None:
        raise OperatorError("compress: LLM stream ended without a completion")

    if final.interrupted:
        return None

    tc = _pick_compress_tool_call(final.tool_calls)
    if tc is None:
        raise OperatorError(_no_tool_message(final.text))

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
        raise OperatorError(f"compress_collate: {e}") from e

    _log.info(
        "compress_collate resolved address=%s slug=%s disk_lines=%s..%s (1-based inclusive)",
        address_str,
        slug,
        start_line,
        end_line,
    )

    collate_storage = await CollateOperator.run_collate(
        session=session,
        narrative=narrative,
        id=slug,
        address_str=address_str,
        start_line=start_line,
        end_line=end_line,
        pins=pins or [],
        unpins=unpins or [],
        llm_id=llm_id,
        reasoning=reasoning,
        on_token=on_token,
        cancel_event=cancel_event,
        summary_guidance=summary_guide.strip() if summary_guide and summary_guide.strip() else None,
    )

    # Record node size after collate for delta tracking (non-fatal if it fails).
    try:
        new_text = target.md_path().read_text(encoding="utf-8")
        new_size = measure_visible_bytes(get_visible_text(new_text))
        set_last_compress_size(target, new_size, collate_storage)
    except Exception:
        _log.debug("compress: failed to record last_size in front matter", exc_info=True)

    return collate_storage
