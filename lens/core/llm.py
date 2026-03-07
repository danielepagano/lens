"""LLM text generation via streaming chat completions.

Configuration is read from the project's ``lens.toml``. Add one or more
``[[llm]]`` entries; the first one is used by default unless a specific
``id`` is requested.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import tomllib
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from lens.core.annotations import encode_ai_secrets

logger = logging.getLogger(__name__)

# Maximum number of consecutive command-tool round-trips per response.
_MAX_COMMAND_TOOL_ITERATIONS = 20

CommandToolFn = Callable[[dict[str, Any], Path], Awaitable[str]]


class LLMError(Exception):
    """Raised when LLM configuration is invalid or an API call fails."""


@dataclass(slots=True)
class _LLMConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float
    timeout_seconds: int


def _load_config(project_root: Path, llm_id: str | None) -> tuple[_LLMConfig, bool]:
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        raise LLMError("lens.toml not found; run 'lens init' first")

    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)

    verbose_llm: bool = bool(config.get("project", {}).get("verbose_llm", False)) or bool(config.get("dataset", {}).get("verbose_llm", False))

    llm_list: list[dict[str, Any]] = config.get("llm", [])
    if not llm_list:
        raise LLMError(
            "no [[llm]] entries found in lens.toml; "
            "add at least one LLM configuration (see README for details)"
        )

    raw: dict[str, Any] | None = None
    if llm_id is not None:
        for entry in llm_list:
            if entry.get("id") == llm_id:
                raw = entry
                break
        if raw is None:
            ids = [e.get("id") for e in llm_list]
            raise LLMError(
                f"no [[llm]] entry with id={llm_id!r} in lens.toml "
                f"(configured ids: {ids})"
            )
    else:
        raw = llm_list[0]

    base_url: str = raw.get("base_url", "")
    if not base_url:
        raise LLMError("[[llm]] entry is missing required field 'base_url'")

    model: str = raw.get("model", "")

    api_key_env: str = raw.get("api_key_env", "")
    api_key = ""
    if api_key_env:
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise LLMError(
                f"environment variable {api_key_env!r} "
                f"(configured in [[llm]] api_key_env) is not set"
            )

    return (
        _LLMConfig(
            base_url=base_url,
            model=model,
            api_key=api_key,
            temperature=float(raw.get("temperature", 0.8)),
            timeout_seconds=int(raw.get("timeout_seconds", 120)),
        ),
        verbose_llm,
    )


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class FinalPayload:
    text: str
    tool_call: ToolCall | None
    usage: dict[str, int] | None
    interrupted: bool


@dataclass(slots=True)
class StreamEvent:
    preview: str | None = None
    final: FinalPayload | None = None


def _format_messages(messages: list[dict[str, Any]]) -> str:
    """Format messages as a human-readable block for logging."""
    sep = "─" * 60
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        parts.append(f"[{role}]\n{content}")
    return f"{sep}\n" + f"\n{sep}\n".join(parts) + f"\n{sep}"


# (open_tag, close_tag) for thinking blocks; order matters for "earliest" match.
_THINK_TAG_PAIRS: list[tuple[str, str]] = [
    ("<think>", "</think>"),
    ("<thinking>", "</thinking>"),
]


def _strip_think_tags(chunk: str, inside_close: str | None) -> tuple[str, str | None]:
    """Strip thinking blocks from chunk (streaming-safe). Supports multiple tag styles.

    Returns (visible_text, new_inside_close). When inside_close is set we suppress
    content until we see that closing tag.
    """
    if not chunk:
        return ("", inside_close)
    if inside_close is not None:
        end_idx = chunk.find(inside_close)
        if end_idx == -1:
            return ("", inside_close)
        rest = chunk[end_idx + len(inside_close) :]
        return _strip_think_tags(rest, None)
    result: list[str] = []
    i = 0
    while i < len(chunk):
        best_open: int | None = None
        best_open_len = 0
        best_close = ""
        for open_tag, close_tag in _THINK_TAG_PAIRS:
            idx = chunk.find(open_tag, i)
            if idx != -1 and (best_open is None or idx < best_open):
                best_open = idx
                best_open_len = len(open_tag)
                best_close = close_tag
        if best_open is None or not best_close:
            result.append(chunk[i:])
            return ("".join(result), None)
        result.append(chunk[i:best_open])
        end_idx = chunk.find(best_close, best_open + best_open_len)
        if end_idx == -1:
            result.append(chunk[best_open + best_open_len :])
            return ("".join(result), best_close)
        i = end_idx + len(best_close)
    return ("".join(result), None)


def _strip_preview(chunk: str, mid_comment: bool) -> tuple[str, bool]:
    """Strip HTML comments from chunk for safe streaming preview.

    Returns (preview_string, new_mid_comment). Preview is empty when inside
    a comment and the chunk does not contain the closing -->.
    """
    if not chunk:
        return ("", mid_comment)

    if mid_comment:
        end_idx = chunk.find("-->")
        if end_idx == -1:
            return ("", True)
        mid_comment = False
        rest = chunk[end_idx + 3 :]
        return _strip_preview(rest, mid_comment)

    result: list[str] = []
    i = 0
    while i < len(chunk):
        start_idx = chunk.find("<!--", i)
        if start_idx == -1:
            result.append(chunk[i:])
            return ("".join(result), False)
        result.append(chunk[i:start_idx])
        end_idx = chunk.find("-->", start_idx + 4)
        if end_idx == -1:
            return ("".join(result), True)
        i = end_idx + 3
    return ("".join(result), False)


async def _stream_once(
    messages: list[dict[str, Any]],
    cfg: _LLMConfig,
    verbose: bool,
    *,
    stop_sequences: list[str] | None,
    tools: list[dict[str, Any]] | None,
    cancel_event: asyncio.Event,
    enable_thinking: bool = False,
) -> AsyncGenerator[StreamEvent, None]:
    """Execute one HTTP streaming request.

    Yields zero or more ``StreamEvent(preview=...)`` during generation,
    then exactly one ``StreamEvent(final=...)`` at the end.

    Does **not** install a SIGINT handler or raise ``KeyboardInterrupt``
    — the caller (``generate_stream``) manages that.
    """
    url = f"{cfg.base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": cfg.temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if cfg.model:
        payload["model"] = cfg.model
    if stop_sequences:
        payload["stop"] = stop_sequences
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if enable_thinking:
        payload["reasoning"] = {"effort": "medium", "include_thought": False}
    else:
        payload["reasoning"] = {"effort": "none"}
        payload["enable_thinking"] = False
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        working = [dict(m) for m in messages]
        if working and working[0].get("role") == "system":
            raw_content = working[0].get("content")
            content = raw_content if isinstance(raw_content, str) else ""
            if "/no_think" not in content and "/think" not in content:
                working[0] = {**working[0], "content": "/no_think\n\n" + content}
        payload["messages"] = working

    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    response_parts: list[str] = []
    raw_response_parts: list[str] = []
    chunks: list[str] = []
    usage: dict[str, int] | None = None
    mid_comment = False
    think_close: str | None = None
    interrupted = False

    tool_calls_by_index: dict[int, dict[str, Any]] = {}

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise LLMError(
                        f"LLM API returned HTTP {response.status_code}: {body.decode()}"
                    )

                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        interrupted = True
                        break

                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break

                    try:
                        data: dict[str, Any] = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("could not decode LLM chunk: %s", data_str)
                        continue

                    if data.get("usage") is not None:
                        raw_usage: dict[str, Any] = data["usage"]
                        prompt_details: dict[str, Any] = raw_usage.get("prompt_tokens_details") or {}
                        usage = {
                            "prompt_tokens": int(raw_usage.get("prompt_tokens", 0)),
                            "completion_tokens": int(raw_usage.get("completion_tokens", 0)),
                            "total_tokens": int(raw_usage.get("total_tokens", 0)),
                            "cached_tokens": int(prompt_details.get("cached_tokens", 0)),
                        }
                        logger.info(
                            "\n\nLLM usage — prompt: %s tokens, completion: %s tokens, total: %s tokens, cached: %s tokens",
                            usage.get("prompt_tokens", "?"),
                            usage.get("completion_tokens", "?"),
                            usage.get("total_tokens", "?"),
                            usage.get("cached_tokens", "?"),
                        )

                    choices: list[Any] = data.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})

                    content: str | None = delta.get("content")
                    reasoning_content: str | None = delta.get("reasoning_content")
                    if reasoning_content and verbose:
                        raw_response_parts.append(reasoning_content)
                    if content:
                        if verbose:
                            raw_response_parts.append(content)
                        content, think_close = _strip_think_tags(content, think_close)
                        if content:
                            response_parts.append(content)
                            chunks.append(content)
                            preview, mid_comment = _strip_preview(content, mid_comment)
                            if preview:
                                yield StreamEvent(preview=preview)

                    tc_list: list[Any] = delta.get("tool_calls") or []
                    for tc in tc_list:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_by_index:
                            tool_calls_by_index[idx] = {
                                "id": "",
                                "name": "",
                                "arguments_fragments": [],
                            }
                        acc = tool_calls_by_index[idx]
                        if tc.get("id"):
                            acc["id"] = tc["id"]
                        # Defensive: inject type if missing (LM Studio quirk)
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            acc["name"] = fn["name"]
                        if fn.get("arguments"):
                            acc["arguments_fragments"].append(fn["arguments"])

    except httpx.TimeoutException as exc:
        raise LLMError(
            f"LLM request timed out after {cfg.timeout_seconds}s"
        ) from exc
    except httpx.RequestError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    full_text = "".join(chunks)
    encoded_text = encode_ai_secrets(full_text)

    tool_call: ToolCall | None = None
    fold_error = False
    if tool_calls_by_index:
        ordered = [tool_calls_by_index[k] for k in sorted(tool_calls_by_index)]
        while len(ordered) > 1:
            last_acc = ordered.pop()
            prev_acc = ordered[-1]
            raw_last = "".join(last_acc["arguments_fragments"])
            try:
                last_args: dict[str, Any] = json.loads(raw_last) if raw_last else {}
            except json.JSONDecodeError:
                last_args = {}
            if prev_acc.get("arguments_parsed") is None:
                raw_prev = "".join(prev_acc["arguments_fragments"])
                try:
                    prev_acc["arguments_parsed"] = (
                        json.loads(raw_prev) if raw_prev else {}
                    )
                except json.JSONDecodeError:
                    prev_acc["arguments_parsed"] = {}
            if "chain" in prev_acc["arguments_parsed"]:
                logger.error(
                    "Lens folding: previous tool call already has chain; "
                    "cannot fold multiple tool calls"
                )
                fold_error = True
                interrupted = True
                break
            prev_acc["arguments_parsed"]["chain"] = {
                "name": last_acc["name"],
                "id": last_acc["id"] or None,
                "arguments": last_args,
            }
        if not fold_error and ordered:
            acc = ordered[0]
            if acc.get("arguments_parsed") is None:
                raw_args = "".join(acc["arguments_fragments"])
                try:
                    parsed_args: dict[str, Any] = (
                        json.loads(raw_args) if raw_args else {}
                    )
                except json.JSONDecodeError:
                    parsed_args = {}
            else:
                parsed_args = acc["arguments_parsed"]
            if acc["name"]:
                tool_call = ToolCall(
                    id=acc["id"],
                    name=acc["name"],
                    arguments=parsed_args if isinstance(parsed_args, dict) else {},  # pyright: ignore[reportUnnecessaryIsInstance]
                )

    if verbose:
        sep = "─" * 60
        if raw_response_parts:
            logger.info(
                "LLM RESPONSE (raw, reasoning/think tags not saved)\n%s\n%s\n%s",
                sep,
                "".join(raw_response_parts),
                sep,
            )
        if response_parts:
            logger.info("LLM RESPONSE\n%s\n%s\n%s", sep, "".join(response_parts), sep)

    yield StreamEvent(
        final=FinalPayload(
            text=encoded_text,
            tool_call=tool_call,
            usage=usage,
            interrupted=interrupted,
        )
    )


async def generate_stream(
    messages: list[dict[str, Any]],
    project_root: Path,
    *,
    llm_id: str | None = None,
    stop_sequences: list[str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    cancel_event: asyncio.Event | None = None,
    command_tool_handlers: dict[str, CommandToolFn] | None = None,
    enable_thinking: bool = False,
) -> AsyncGenerator[StreamEvent, None]:
    """Stream LLM output as structured events.

    Yields ``StreamEvent(preview=...)`` during generation (HTML comments
    stripped) and a single ``StreamEvent(final=...)`` at the end.

    When *command_tool_handlers* is provided and the LLM calls a tool whose
    name appears in that mapping, the handler is executed immediately, the
    result is appended to the working message list, and the LLM is re-invoked
    — all without exiting this generator.  Preview events from every iteration
    are forwarded to the caller.

    Tool calls whose names are **not** in *command_tool_handlers* (i.e.
    operator tools) cause the generator to return a ``FinalPayload`` with
    ``tool_call`` set, exactly as before — the caller dispatches them.
    """
    _cancel = cancel_event if cancel_event is not None else asyncio.Event()
    _interrupted = False
    _sigint_installed = False

    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        nonlocal _interrupted
        _interrupted = True
        _cancel.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
        _sigint_installed = True
    except (NotImplementedError, ValueError):
        pass

    cfg, verbose = _load_config(project_root, llm_id)

    if verbose:
        logger.info("LLM PROMPT\n%s", _format_messages(messages))

    working_messages: list[dict[str, Any]] = list(messages)
    last_usage: dict[str, int] | None = None
    half_limit = _MAX_COMMAND_TOOL_ITERATIONS // 2
    warned_at_half = False

    try:
        for iteration in range(_MAX_COMMAND_TOOL_ITERATIONS + 1):
            final: FinalPayload | None = None

            async for event in _stream_once(
                working_messages,
                cfg,
                verbose,
                stop_sequences=stop_sequences,
                tools=tools,
                cancel_event=_cancel,
                enable_thinking=enable_thinking,
            ):
                if event.preview:
                    yield event
                elif event.final:
                    final = event.final
                    if event.final.usage:
                        last_usage = event.final.usage

            if final is None:
                # Should not happen; guard against empty responses
                break

            if final.interrupted:
                yield StreamEvent(
                    final=FinalPayload(
                        text=final.text,
                        tool_call=final.tool_call,
                        usage=last_usage,
                        interrupted=True,
                    )
                )
                _interrupted = True
                break

            if verbose and final.tool_call is not None:
                logger.info(
                    "LLM TOOL CALL REQUEST — %s(%s)",
                    final.tool_call.name,
                    json.dumps(final.tool_call.arguments),
                )

            # ── Command tool path ─────────────────────────────────────────
            if (
                final.tool_call is not None
                and command_tool_handlers is not None
                and final.tool_call.name in command_tool_handlers
            ):
                handler = command_tool_handlers[final.tool_call.name]
                # Strip "chain" key before passing to handler — chain is an
                # operator concept and does not apply to command tools.
                handler_args = {
                    k: v
                    for k, v in final.tool_call.arguments.items()
                    if k != "chain"
                }
                result = await handler(handler_args, project_root)
                if not warned_at_half and iteration + 1 >= half_limit:
                    warned_at_half = True
                    warning = (
                        f"\n\n[Warning: you have used {iteration + 1} of "
                        f"{_MAX_COMMAND_TOOL_ITERATIONS} allowed tool calls "
                        "this response.]"
                    )
                    result = result + warning
                    yield StreamEvent(preview=warning)
                if verbose:
                    logger.info(
                        "LLM TOOL CALL RESPONSE — %s\n%s",
                        final.tool_call.name,
                        result,
                    )

                working_messages.append(
                    {
                        "role": "assistant",
                        "content": final.text or None,
                        "tool_calls": [
                            {
                                "id": final.tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": final.tool_call.name,
                                    "arguments": json.dumps(
                                        final.tool_call.arguments
                                    ),
                                },
                            }
                        ],
                    }
                )
                working_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": final.tool_call.id,
                        "content": result,
                    }
                )
                continue

            # ── Operator tool or normal end ───────────────────────────────
            yield StreamEvent(
                final=FinalPayload(
                    text=final.text,
                    tool_call=final.tool_call,
                    usage=last_usage,
                    interrupted=False,
                )
            )
            break

        else:
            # Exceeded maximum command tool iterations; return message, do not abort
            logger.warning(
                "generate_stream: exceeded %d command tool iterations",
                _MAX_COMMAND_TOOL_ITERATIONS,
            )
            limit_msg = (
                "You have exceeded the maximum number of tool calls per response "
                f"(limit: {_MAX_COMMAND_TOOL_ITERATIONS})."
            )
            yield StreamEvent(
                final=FinalPayload(
                    text=limit_msg,
                    tool_call=None,
                    usage=last_usage,
                    interrupted=False,
                )
            )

    finally:
        if _sigint_installed:
            loop.remove_signal_handler(signal.SIGINT)

    if _interrupted:
        raise KeyboardInterrupt
