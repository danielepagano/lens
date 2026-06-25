"""Structured LLM generation output: prose vs tool-call metadata and persist/stream/log composers."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

CommandToolFn = Callable[[dict[str, Any], Path], Awaitable[str]]

logger = logging.getLogger(__name__)

_TOOL_CALL_FENCE_RE = re.compile(
    r"```tool-call\n.*?^```\s*",
    re.MULTILINE | re.DOTALL,
)

_TOOL_RESULT_MAX_CHARS = 2000


class ComposePolicy(Enum):
    """How to turn generation segments into text for persistence."""

    NARRATIVE = "narrative"
    """Interleave prose and tool-call fences in generation order (inline operators)."""
    PROSE_ONLY = "prose_only"
    """Strip tool-call fences; keep only prose segments."""
    AUDIT_COMMENT = "audit_comment"
    """Remember-style: tool-call fences verbatim; other prose in HTML audit comments."""


class StreamComposePolicy(Enum):
    """How to format tool-call segments for streaming / SSE display."""

    INTERLEAVE = "interleave"
    """Current behavior: tool-call fences appear as raw markdown in the token stream."""
    PROSE_ONLY = "prose_only"
    """Tool-call fences are suppressed — clients see only prose tokens."""
    STRUCTURED = "structured"
    """Tool calls emit typed events (tool name, arg summary) instead of raw fences."""


@dataclass(frozen=True)
class GenerationSegment:
    kind: Literal["prose", "tool_call"]
    text: str


@dataclass
class GenerationArtifacts:
    """Split LLM generation output before persist composition."""

    segments: list[GenerationSegment] = field(default_factory=lambda: list[GenerationSegment]())
    failure_result_fences: list[str] = field(default_factory=lambda: list[str]())
    interrupted: bool = False

    def has_content(self) -> bool:
        if self.failure_result_fences:
            return True
        return any(seg.text.strip() for seg in self.segments)


def replace_narrative_prose(artifacts: GenerationArtifacts, text: str) -> None:
    """Replace prose segments with *text*; preserve tool-call segments in order."""
    tool_segments = [seg for seg in artifacts.segments if seg.kind == "tool_call"]
    artifacts.segments.clear()
    stripped = text.strip()
    if stripped:
        artifacts.segments.append(GenerationSegment("prose", text if text.endswith("\n") else text + "\n"))
    artifacts.segments.extend(tool_segments)


def _audit_comment(tag: str, text: str) -> str:
    safe = text.replace("-->", "→").replace("<!--", "⟨")
    return f"<!-- {tag}:\n{safe}\n-->"


def format_tool_call_fence(name: str, arguments: dict[str, Any], *, response_char_len: int | None) -> str:
    """Fenced block: tool request JSON plus optional response size.

    Always includes a newline before the opening ``` and after the closing ``` so
    the fence never abuts adjacent prose or other fences, which would mangle the
    markdown.
    """
    req = json.dumps(arguments, indent=2, ensure_ascii=False, default=str)
    lines = [
        "```tool-call",
        f"Called Tool '{name}' ({response_char_len if response_char_len else 'zero'} bytes)",
        req,
        "```",
    ]
    return "\n" + "\n".join(lines) + "\n"


def format_tool_result_fence(result: str, *, max_chars: int = _TOOL_RESULT_MAX_CHARS) -> str:
    body = result.strip()
    if len(body) > max_chars:
        body = f"{body[:max_chars]}…"
    return f"```tool-result\n{body}\n```\n"


def _kb_path_for_tool_log(project_root: Path, raw_id: str) -> str:
    from lens.core.knowledge import parse_id

    try:
        type_name, key = parse_id(raw_id)
        return f"knowledge/{type_name}/{key}.md"
    except ValueError:
        return raw_id


def _compact_kb_patch_summary(args: dict[str, Any]) -> str:
    parts: list[str] = []
    raw_id = args.get("id")
    if isinstance(raw_id, str):
        parts.append(f"id={raw_id}")
    patches_raw = args.get("patches")
    if not isinstance(patches_raw, list):
        return ", ".join(parts)
    patches = cast(list[Any], patches_raw)
    parts.append(f"patches={len(patches)}")
    if not patches:
        return ", ".join(parts)
    first_raw = patches[0]
    if not isinstance(first_raw, dict):
        return ", ".join(parts)
    first = cast(dict[str, Any], first_raw)
    start = first.get("start")
    if not isinstance(start, dict):
        return ", ".join(parts)
    start_d = cast(dict[str, Any], start)
    target = start_d.get("target")
    if isinstance(target, str) and target:
        snippet = target if len(target) <= 80 else f"{target[:77]}..."
        parts.append(f"start.target={snippet!r}")
    return ", ".join(parts)


def _tool_handler_succeeded(result: str, *, operator_name: str | None) -> bool:
    stripped = result.strip()
    if not stripped:
        return False
    if operator_name == "remember":
        return stripped.startswith("OK:")
    if stripped.startswith("(error:"):
        return False
    return True


def wrap_command_tool_handlers_for_audit(
    handlers: dict[str, CommandToolFn],
    *,
    failure_result_fences: list[str],
    operator_name: str | None,
    project_root: Path,
) -> dict[str, CommandToolFn]:
    """Record failed tool results as ``tool-result`` fences (remember-style audit)."""

    wrapped: dict[str, CommandToolFn] = {}

    for name, handler in handlers.items():

        async def _wrapped(
            args: dict[str, Any],
            _root: Path,
            *,
            _handler: CommandToolFn = handler,
            _name: str = name,
        ) -> str:
            result = await _handler(args, project_root)
            if _tool_handler_succeeded(result, operator_name=operator_name):
                return result
            first_line = result.strip().split("\n", 1)[0]
            if operator_name == "remember":
                summary = _compact_kb_patch_summary(args)
                kb_path = ""
                raw_id = args.get("id")
                if isinstance(raw_id, str):
                    kb_path = _kb_path_for_tool_log(project_root, raw_id)
                logger.warning(
                    "remember: %s failed on %s (%s): %s",
                    _name,
                    kb_path or "?",
                    summary,
                    first_line,
                )
            else:
                logger.warning(
                    "%s tool %s failed: %s",
                    operator_name or "llm",
                    _name,
                    first_line,
                )
            fence = format_tool_result_fence(result)
            if fence not in failure_result_fences:
                failure_result_fences.append(fence)
            return result

        wrapped[name] = _wrapped

    return wrapped


def compose_generation_artifacts(
    artifacts: GenerationArtifacts,
    policy: ComposePolicy,
    *,
    audit_comment_tag: str = "remember",
) -> str:
    if policy == ComposePolicy.NARRATIVE:
        return _compose_narrative(artifacts)
    if policy == ComposePolicy.PROSE_ONLY:
        return _compose_prose_only(artifacts)
    if policy == ComposePolicy.AUDIT_COMMENT:
        return _compose_audit_comment(artifacts, tag=audit_comment_tag)
    raise ValueError(f"unknown compose policy: {policy!r}")


def _compose_prose_only(artifacts: GenerationArtifacts) -> str:
    parts: list[str] = []
    for seg in artifacts.segments:
        if seg.kind == "prose" and seg.text:
            parts.append(seg.text)
    return "".join(parts)


def _compose_narrative(artifacts: GenerationArtifacts) -> str:
    parts: list[str] = []
    for seg in artifacts.segments:
        if seg.text:
            parts.append(seg.text)
    base = "".join(parts)
    if not artifacts.failure_result_fences:
        return base
    audit = "\n\n".join(block.rstrip() for block in artifacts.failure_result_fences).strip()
    if not audit:
        return base
    if not base.strip():
        return f"\n\n{audit}\n"
    return f"{base.rstrip()}\n\n{audit}\n"


def _compose_audit_comment(artifacts: GenerationArtifacts, *, tag: str) -> str:
    raw = _compose_audit_comment_body(artifacts, tag=tag)
    if not artifacts.failure_result_fences:
        return raw
    audit = "\n\n".join(block.rstrip() for block in artifacts.failure_result_fences).strip()
    if not audit:
        return raw
    if not raw.strip():
        return f"\n\n{audit}\n"
    return f"{raw.rstrip()}\n\n{audit}\n"


def _compose_audit_comment_body(artifacts: GenerationArtifacts, *, tag: str) -> str:
    combined = "".join(seg.text for seg in artifacts.segments).strip()
    if not combined:
        return ""
    if "```tool-call" not in combined:
        if tag == "remember":
            return f"\n\n{_audit_comment(tag, combined)}\n"
        return f"\n\n{combined}\n"
    parts: list[str] = []
    pos = 0
    for m in _TOOL_CALL_FENCE_RE.finditer(combined):
        before = combined[pos : m.start()].strip()
        if before:
            parts.append(_audit_comment(tag, before))
        parts.append(m.group(0).rstrip())
        pos = m.end()
    tail = combined[pos:].strip()
    if tail:
        parts.append(_audit_comment(tag, tail))
    out = "\n\n".join(parts).strip()
    return f"\n\n{out}\n" if out else ""


_compose_policies: dict[str, ComposePolicy] = {}


def register_compose_policy(operator_name: str, policy: ComposePolicy) -> None:
    """Override persist composition for an operator (e.g. narrative interleave)."""
    _compose_policies[operator_name] = policy


def get_compose_policy(operator_name: str | None) -> ComposePolicy:
    if operator_name is None:
        return ComposePolicy.AUDIT_COMMENT
    return _compose_policies.get(operator_name, ComposePolicy.AUDIT_COMMENT)


register_compose_policy("kb_edit", ComposePolicy.PROSE_ONLY)
for _inline_op in ("write", "play", "chat", "design", "edit", "advance"):
    register_compose_policy(_inline_op, ComposePolicy.NARRATIVE)


def audit_comment_tag_for_operator(operator_name: str | None) -> str:
    if operator_name == "remember":
        return "remember"
    return "tool-audit"


def compose_for_operator(
    artifacts: GenerationArtifacts,
    operator_name: str | None,
) -> str:
    policy = get_compose_policy(operator_name)
    return compose_generation_artifacts(
        artifacts,
        policy,
        audit_comment_tag=audit_comment_tag_for_operator(operator_name),
    )


def compose_audit_from_combined_text(raw: str, *, tag: str = "remember") -> str:
    """Compose audit-comment output from a single string (may contain tool-call fences)."""
    artifacts = GenerationArtifacts(
        segments=[GenerationSegment("prose", raw)] if raw.strip() else [],
    )
    return _compose_audit_comment(artifacts, tag=tag)


def compose_audit_suffix(
    raw: str,
    failure_result_fences: list[str],
    *,
    tag: str = "remember",
) -> str:
    artifacts = GenerationArtifacts(
        segments=[GenerationSegment("prose", raw)] if raw.strip() else [],
        failure_result_fences=list(failure_result_fences),
    )
    return _compose_audit_comment(artifacts, tag=tag)


# ---------------------------------------------------------------------------
# Stream & logging composers
# ---------------------------------------------------------------------------

_StreamChunk = tuple[Literal["preview", "tool_event", "skip"], str | dict[str, Any] | None]


def _format_tool_call_summary(name: str, arguments: dict[str, Any], *, response_char_len: int | None) -> str:
    """Compact human-readable summary for a tool call (logging & structured preview)."""
    parts: list[str] = []
    parts.append(f"Tool '{name}'")
    if arguments:
        arg_keys = list(arguments.keys())
        if arg_keys:
            parts.append(f"args=[{', '.join(arg_keys)}]")
    if response_char_len is not None:
        parts.append(f"response={response_char_len}B")
    return " · ".join(parts)


def _compose_stream_interleave(segment: GenerationSegment) -> _StreamChunk:
    """Unchanged raw markdown fences for tool calls."""
    return ("preview", segment.text)


def _compose_stream_prose_only(segment: GenerationSegment) -> _StreamChunk:
    """Suppress tool_calls from the preview stream entirely."""
    if segment.kind == "tool_call":
        return ("skip", None)
    return ("preview", segment.text)


def _compose_stream_structured(segment: GenerationSegment) -> _StreamChunk:
    """Emit a structured tool_event dict for tool calls."""
    if segment.kind == "tool_call":
        return ("tool_event", {"fence_text": segment.text})
    return ("preview", segment.text)


_stream_compose_policies: dict[str, StreamComposePolicy] = {}


def register_stream_compose_policy(operator_name: str, policy: StreamComposePolicy) -> None:
    _stream_compose_policies[operator_name] = policy


def get_stream_compose_policy(operator_name: str | None) -> StreamComposePolicy:
    if operator_name is None:
        return StreamComposePolicy.INTERLEAVE
    return _stream_compose_policies.get(operator_name, StreamComposePolicy.INTERLEAVE)


def compose_for_stream(
    artifacts: GenerationArtifacts,
    operator_name: str | None,
) -> list[tuple[Literal["preview", "tool_event"], str | dict[str, Any]]]:
    """Compose generation segments into stream-friendly chunks.

    Returns a list of (kind, content) tuples:
    - ``("preview", text)`` — forward to the token/SSE preview handler.
    - ``("tool_event", payload)`` — structured dict (see
      :func:`compose_tool_call_for_stream` for the shape).

    ``PROSE_ONLY`` policy filters out tool-call segments entirely;
    ``INTERLEAVE`` emits raw markdown fences as preview strings;
    ``STRUCTURED`` emits tool_event dicts for tool-call segments.
    """
    policy = get_stream_compose_policy(operator_name)
    results: list[tuple[Literal["preview", "tool_event"], str | dict[str, Any]]] = []
    for seg in artifacts.segments:
        if seg.kind == "prose":
            if seg.text:
                results.append(("preview", seg.text))
        elif seg.kind == "tool_call":
            if policy == StreamComposePolicy.INTERLEAVE:
                chunk = _compose_stream_interleave(seg)
                if chunk[0] != "skip":
                    results.append(chunk)  # type: ignore[arg-type]
            elif policy == StreamComposePolicy.PROSE_ONLY:
                chunk = _compose_stream_prose_only(seg)
                if chunk[0] != "skip":
                    results.append(chunk)  # type: ignore[arg-type]
            elif policy == StreamComposePolicy.STRUCTURED:
                chunk = _compose_stream_structured(seg)
                if chunk[0] != "skip":
                    results.append(chunk)  # type: ignore[arg-type]
    return results


def format_tool_event_for_log(
    name: str,
    arguments: dict[str, Any],
    *,
    response_char_len: int | None,
) -> str:
    """Compact operator-aware log line for a tool call (avoids dumping full fence bodies)."""
    return _format_tool_call_summary(name, arguments, response_char_len=response_char_len)


# Default stream compose policy: inline narrative ops stick with INTERLEAVE;
# remember-like paths default to PROSE_ONLY (cleaner preview).
register_stream_compose_policy("remember", StreamComposePolicy.PROSE_ONLY)
register_stream_compose_policy("kb_edit", StreamComposePolicy.PROSE_ONLY)
for _inline_op in ("write", "play", "chat", "edit", "advance", "compress", "collate", "section"):
    register_stream_compose_policy(_inline_op, StreamComposePolicy.INTERLEAVE)
register_stream_compose_policy("design", StreamComposePolicy.STRUCTURED)
def compose_tool_call_for_stream(
    name: str,
    arguments: dict[str, Any],
    *,
    response_char_len: int | None,
    operator_name: str | None,
    encode_fence: Callable[[str], str] | None = None,
) -> _StreamChunk:
    """Compose a single tool-call event for the stream preview.

    Returns a ``(kind, content)`` tuple.  Caller yields a ``StreamEvent``
    with ``preview=content`` (string) or ``tool_event=content`` (dict)
    or nothing (skip).  *encode_fence* is called on the markdown fence
    text when ``INTERLEAVE`` policy is active (e.g. ``encode_ai_secrets``).
    """
    fence = format_tool_call_fence(name, arguments, response_char_len=response_char_len)
    policy = get_stream_compose_policy(operator_name)

    if policy == StreamComposePolicy.INTERLEAVE:
        encoded = encode_fence(fence) if encode_fence else fence
        return ("preview", encoded)
    if policy == StreamComposePolicy.PROSE_ONLY:
        return ("skip", None)
    if policy == StreamComposePolicy.STRUCTURED:
        summary = _format_tool_call_summary(name, arguments, response_char_len=response_char_len)
        payload: dict[str, Any] = {
            "name": name,
            "summary": summary,
            "fence_text": fence,
        }
        return ("tool_event", payload)
    return ("preview", fence)
