"""LLM text generation via streaming chat completions.

Configuration is read from the project's ``lens.toml``. Add one or more
``[[llm]]`` entries; the first one is used by default unless a specific
``id`` is requested.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import signal
import time
import tomllib
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from lens.core.annotations import encode_ai_secrets

logger = logging.getLogger(__name__)

# Optional UI progress hook (e.g. SSE) — set by ``llm_progress_scope`` from the server.
LLMProgressHandler = Callable[[str, dict[str, Any]], Awaitable[None]]
_llm_progress_cb: contextvars.ContextVar[LLMProgressHandler | None] = contextvars.ContextVar(
    "lens_llm_progress_cb",
    default=None,
)


def _llm_api_host(base_url: str) -> str:
    try:
        netloc = urlparse(base_url).netloc
        return netloc if netloc else base_url
    except Exception:
        return base_url


def _first_phase_time_remaining(t_request_start: float, budget_s: float) -> float:
    """Seconds left for headers + first SSE ``data:`` line (wall clock from request start)."""
    return max(0.001, budget_s - (time.monotonic() - t_request_start))


async def _emit_llm_progress(phase: str, detail: dict[str, Any]) -> None:
    cb = _llm_progress_cb.get()
    if cb is None:
        return
    try:
        await cb(phase, detail)
    except Exception:
        logger.exception("LLM progress handler failed (phase=%s)", phase)


@asynccontextmanager
async def llm_progress_scope(handler: LLMProgressHandler | None):
    """Bind an async progress callback for nested ``generate_stream`` / ``generate_text`` calls."""
    if handler is None:
        yield
        return
    token = _llm_progress_cb.set(handler)
    try:
        yield
    finally:
        _llm_progress_cb.reset(token)


# Maximum number of consecutive command-tool round-trips per response.
_MAX_COMMAND_TOOL_ITERATIONS = 20

# When ``enable_thinking`` is True, reasoning budget for providers that support
# it (e.g. OpenRouter). Medium leaves more room for visible completion than high.
_REASONING_EFFORT = "medium"

CommandToolFn = Callable[[dict[str, Any], Path], Awaitable[str]]
PreviewHandler = Callable[[str], Awaitable[None]]


class LLMError(Exception):
    """Raised when LLM configuration is invalid or an API call fails."""


@dataclass(slots=True)
class _LLMConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float
    first_token_timeout_seconds: float
    timeout_seconds: float
    reasoning_effort: str
    enable_thinking: bool


def _load_config(
    project_root: Path,
    llm_id: str | None,
    operator_name: str | None = None,
) -> tuple[_LLMConfig, bool]:
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        raise LLMError("lens.toml not found; run 'lens init' first")

    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)

    verbose_llm: bool = bool(config.get("project", {}).get("verbose_llm", False)) or bool(config.get("dataset", {}).get("verbose_llm", False))

    # Per-operator overrides from [operator.<name>] section.
    op_cfg: dict[str, Any] = {}
    if operator_name:
        op_cfg = config.get("operator", {}).get(operator_name, {})

    # Resolve the effective LLM ID: CLI arg > operator default > first entry.
    if llm_id is None and "llm" in op_cfg:
        llm_id = op_cfg["llm"]

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

    # Precedence for each tunable field: op_cfg > [[llm]] entry > hardcoded default.
    return (
        _LLMConfig(
            base_url=base_url,
            model=model,
            api_key=api_key,
            temperature=float(op_cfg.get("temperature", raw.get("temperature", 0.8))),
            first_token_timeout_seconds=float(op_cfg.get("first_token_timeout_seconds", raw.get("first_token_timeout_seconds", 10))),
            timeout_seconds=float(op_cfg.get("timeout_seconds", raw.get("timeout_seconds", 120))),
            reasoning_effort=str(op_cfg.get("reasoning_effort", raw.get("reasoning_effort", _REASONING_EFFORT))),
            enable_thinking=bool(op_cfg.get("reasoning", raw.get("reasoning", False))),
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
    tool_calls: list[ToolCall]
    usage: dict[str, int] | None
    interrupted: bool


@dataclass(slots=True)
class StreamEvent:
    preview: str | None = None
    final: FinalPayload | None = None


@dataclass(slots=True)
class CommandToolsBundle:
    tools: list[dict[str, Any]] | None
    handlers: dict[str, CommandToolFn] | None


def build_command_tools_bundle(project_root: Path) -> CommandToolsBundle:
    from lens.core.command_tools import get_command_registry

    cmd_registry = get_command_registry(project_root)
    if not cmd_registry:
        return CommandToolsBundle(tools=None, handlers=None)
    tools = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": cmd_def.description,
                "parameters": cmd_def.parameters,
            },
        }
        for name, (cmd_def, _fn) in cmd_registry.items()
    ]
    handlers = {name: fn for name, (_def, fn) in cmd_registry.items()}
    return CommandToolsBundle(tools=tools, handlers=handlers)


def build_kb_patch_whitelist_bundle(allowed_ids: frozenset[str]) -> CommandToolsBundle:
    """Single ``kb_patch`` tool with server-side id whitelist (e.g. remember patches)."""
    from lens.core.command_tools import KB_PATCH_TOOL, kb_patch_handler

    if not allowed_ids:
        return CommandToolsBundle(tools=None, handlers=None)

    allowed_sorted = ", ".join(sorted(allowed_ids))
    extra = (
        " You may only patch these KB ids: "
        f"{allowed_sorted}. Any other id is rejected."
    )

    async def _guarded_kb_patch(
        args: dict[str, Any], project_root: Path
    ) -> str:
        raw_id = args.get("id")
        if not isinstance(raw_id, str) or raw_id not in allowed_ids:
            return (
                "(error: kb_patch may only target these KB objects: "
                f"{allowed_sorted})"
            )
        return await kb_patch_handler(args, project_root)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "kb_patch",
                "description": KB_PATCH_TOOL.description + extra,
                "parameters": KB_PATCH_TOOL.parameters,
            },
        }
    ]
    return CommandToolsBundle(
        tools=tools,
        handlers={"kb_patch": _guarded_kb_patch},
    )


async def collect_final_payload(
    stream: AsyncIterator[StreamEvent],
    *,
    on_preview: PreviewHandler | None,
) -> FinalPayload | None:
    final: FinalPayload | None = None
    async for event in stream:
        if event.preview and on_preview is not None:
            await on_preview(event.preview)
        if event.final is not None:
            final = event.final
            break
    return final


InterruptPolicy = Literal["return_empty", "raise"]


async def generate_text(
    messages: list[dict[str, Any]],
    project_root: Path,
    *,
    llm_id: str | None = None,
    stop_sequences: list[str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    cancel_event: asyncio.Event | None = None,
    command_tool_handlers: dict[str, CommandToolFn] | None = None,
    enable_thinking: bool | None = None,
    reasoning: str | None = None,
    operator_name: str | None = None,
    on_preview: PreviewHandler | None = None,
    interrupt_policy: InterruptPolicy = "return_empty",
    on_llm_error: Callable[[LLMError], Exception] | None = None,
) -> str:
    try:
        final = await collect_final_payload(
            generate_stream(
                messages,
                project_root,
                llm_id=llm_id,
                stop_sequences=stop_sequences,
                tools=tools,
                cancel_event=cancel_event,
                command_tool_handlers=command_tool_handlers,
                enable_thinking=enable_thinking,
                reasoning=reasoning,
                operator_name=operator_name,
            ),
            on_preview=on_preview,
        )
        if final is None:
            logger.error("generate_text: stream ended without a final payload")
            raise LLMError("LLM stream ended without a completion event")
        if final.interrupted:
            if interrupt_policy == "raise":
                raise KeyboardInterrupt
            return ""
        return final.text
    except KeyboardInterrupt:
        if interrupt_policy == "raise":
            raise
        return ""
    except LLMError as e:
        if on_llm_error is not None:
            raise on_llm_error(e) from e
        raise


def _format_messages(messages: list[dict[str, Any]]) -> str:
    """Format messages as a human-readable block for logging."""
    sep = "─" * 60
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        parts.append(f"[{role}]\n{content}")
    return f"{sep}\n" + f"\n{sep}\n".join(parts) + f"\n{sep}"


def _format_tool_call_markdown(
    name: str,
    arguments: dict[str, Any],
    *,
    response_char_len: int | None,
) -> str:
    """Fenced block for streaming and logs: tool request JSON plus optional response size."""
    req = json.dumps(arguments, indent=2, ensure_ascii=False, default=str)
    lines = ["```tool-call", f"Called Tool '{name}' ({response_char_len if response_char_len else 'zero'} bytes)", req]
    lines.append("```")
    return "\n".join(lines) + "\n"


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
    round_index: int = 0,
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
    payload["enable_thinking"] = enable_thinking
    payload["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
    if enable_thinking:
        payload["reasoning"] = {"effort": cfg.reasoning_effort}
    else:
        payload["reasoning"] = {"effort": "none", "enabled": False}
        if not enable_thinking:
            working = [dict(m) for m in messages]
            if working and working[0].get("role") == "system":
                raw_content = working[0].get("content")
                content_str = raw_content if isinstance(raw_content, str) else ""
                if "/no_think" not in content_str and "/think" not in content_str:
                    working[0] = {**working[0], "content": "/no_think\n\n" + content_str}
            payload["messages"] = working

    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    chunks: list[str] = []
    usage: dict[str, int] | None = None
    mid_comment = False
    interrupted = False

    tool_calls_by_index: dict[int, dict[str, Any]] = {}

    host = _llm_api_host(cfg.base_url)
    model_label = cfg.model or "(unspecified)"
    first_token_budget = float(cfg.first_token_timeout_seconds)
    stream_idle_s = float(cfg.timeout_seconds)
    timeout = httpx.Timeout(connect=30.0, read=None, write=120.0, pool=30.0)
    t0 = time.monotonic()
    logger.info(
        "LLM HTTP POST starting round=%s host=%s model=%s first_token_timeout_s=%s stream_idle_timeout_s=%s",
        round_index,
        host,
        model_label,
        first_token_budget,
        stream_idle_s,
    )
    await _emit_llm_progress(
        "http_request",
        {
            "message": "Sending LLM request…",
            "round": round_index,
            "host": host,
            "model": model_label,
        },
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            req = client.build_request("POST", url, json=payload, headers=headers)
            try:
                response = await asyncio.wait_for(
                    client.send(req, stream=True),
                    timeout=_first_phase_time_remaining(t0, first_token_budget),
                )
            except asyncio.TimeoutError as exc:
                logger.error(
                    "LLM HTTP timeout round=%s host=%s phase=first_token after %.2fs (budget=%ss)",
                    round_index,
                    host,
                    time.monotonic() - t0,
                    first_token_budget,
                )
                raise LLMError(
                    f"LLM request produced no response within {cfg.first_token_timeout_seconds}s "
                    "(headers or first stream data; increase [[llm]] first_token_timeout_seconds "
                    "for slow cold starts)"
                ) from exc

            try:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.error(
                        "LLM HTTP error status=%s host=%s round=%s body_prefix=%s",
                        response.status_code,
                        host,
                        round_index,
                        body[:500].decode(errors="replace"),
                    )
                    raise LLMError(
                        f"LLM API returned HTTP {response.status_code}: {body.decode()}"
                    )

                logger.info(
                    "LLM HTTP connected status=200 round=%s (%.2fs to headers)",
                    round_index,
                    time.monotonic() - t0,
                )
                await _emit_llm_progress(
                    "http_stream_open",
                    {
                        "message": "Connected — receiving stream…",
                        "round": round_index,
                        "http_status": 200,
                    },
                )

                line_iter = response.aiter_lines().__aiter__()
                first_phase = True
                while True:
                    if cancel_event.is_set():
                        interrupted = True
                        break

                    try:
                        wait_s = (
                            _first_phase_time_remaining(t0, first_token_budget)
                            if first_phase
                            else stream_idle_s
                        )
                        line = await asyncio.wait_for(line_iter.__anext__(), timeout=wait_s)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError as exc:
                        if first_phase:
                            logger.error(
                                "LLM HTTP timeout round=%s host=%s phase=first_sse_line after %.2fs (budget=%ss)",
                                round_index,
                                host,
                                time.monotonic() - t0,
                                first_token_budget,
                            )
                            raise LLMError(
                                f"LLM stream produced no SSE data within {cfg.first_token_timeout_seconds}s "
                                "from request start (increase [[llm]] first_token_timeout_seconds "
                                "for long provider thinking / cold start)"
                            ) from exc
                        logger.error(
                            "LLM HTTP timeout round=%s host=%s phase=stream_idle after %.2fs (idle_limit=%ss)",
                            round_index,
                            host,
                            time.monotonic() - t0,
                            stream_idle_s,
                        )
                        raise LLMError(
                            f"LLM stream stalled: no data for {cfg.timeout_seconds}s "
                            "(increase [[llm]] timeout_seconds)"
                        ) from exc

                    stripped = line.strip()
                    if not stripped:
                        continue
                    if not stripped.startswith("data:"):
                        continue
                    if first_phase:
                        first_phase = False
                    data_str = stripped[5:].lstrip()
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
                        logger.info("LLM REASONING — %s", reasoning_content)
                    if content:
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
            finally:
                await response.aclose()

    except httpx.TimeoutException as exc:
        logger.error(
            "LLM HTTP timeout round=%s host=%s after %.2fs",
            round_index,
            host,
            time.monotonic() - t0,
        )
        raise LLMError(
            "LLM request timed out (connection or write; try increasing [[llm]] first_token_timeout_seconds)"
        ) from exc
    except httpx.RequestError as exc:
        logger.error(
            "LLM HTTP request error round=%s host=%s: %s",
            round_index,
            host,
            exc,
        )
        raise LLMError(f"LLM request failed: {exc}") from exc

    elapsed = time.monotonic() - t0
    logger.info(
        "LLM HTTP stream finished round=%s host=%s elapsed_s=%.2f interrupted=%s",
        round_index,
        host,
        elapsed,
        interrupted,
    )
    await _emit_llm_progress(
        "http_stream_closed",
        {
            "message": "Stream finished",
            "round": round_index,
            "elapsed_ms": int(elapsed * 1000),
            "interrupted": interrupted,
        },
    )

    full_text = "".join(chunks)
    encoded_text = encode_ai_secrets(full_text)

    parsed_tool_calls: list[ToolCall] = []
    for idx in sorted(tool_calls_by_index):
        acc = tool_calls_by_index[idx]
        raw_args = "".join(acc["arguments_fragments"])
        try:
            parsed_args: dict[str, Any] = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            parsed_args = {}
        if acc["name"]:
            parsed_tool_calls.append(
                ToolCall(
                    id=acc["id"],
                    name=acc["name"],
                    arguments=parsed_args if isinstance(parsed_args, dict) else {},  # pyright: ignore[reportUnnecessaryIsInstance]
                )
            )

    if verbose:
        sep = "─" * 60
        log_body = "".join(chunks)
        for tc in parsed_tool_calls:
            log_body += encode_ai_secrets(
                _format_tool_call_markdown(
                    tc.name, tc.arguments, response_char_len=None
                )
            )
        if log_body.strip():
            logger.info("LLM RESPONSE\n%s\n%s\n%s", sep, log_body, sep)

    yield StreamEvent(
        final=FinalPayload(
            text=encoded_text,
            tool_calls=parsed_tool_calls,
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
    enable_thinking: bool | None = None,
    reasoning: str | None = None,
    operator_name: str | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """Stream LLM output as structured events.

    Yields ``StreamEvent(preview=...)`` during generation (HTML comments
    stripped). Tool calls append a fenced ``tool-call`` block to preview and,
    for command tools, to the accumulated ``final.text``. A single
    ``StreamEvent(final=...)`` ends each outer iteration.

    When *command_tool_handlers* is provided and the LLM returns tool calls
    whose names appear in that mapping, all matching handlers are executed
    immediately, results are appended to the working message list, and the
    LLM is re-invoked — all without exiting this generator. Multiple command
    tool calls in a single LLM response are handled in one iteration.
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
    except (NotImplementedError, ValueError, RuntimeError):
        pass

    cfg, verbose = _load_config(project_root, llm_id, operator_name)
    if reasoning is not None:
        if reasoning == "none":
            cfg = dataclasses.replace(cfg, enable_thinking=False)
        else:
            cfg = dataclasses.replace(cfg, enable_thinking=True, reasoning_effort=reasoning)
    eff_thinking: bool = enable_thinking if enable_thinking is not None else cfg.enable_thinking

    host = _llm_api_host(cfg.base_url)
    model_label = cfg.model or "(unspecified)"
    logger.info(
        "LLM generate_stream start llm_id=%s model=%s host=%s message_count=%d tools=%s",
        llm_id,
        model_label,
        host,
        len(messages),
        "yes" if tools else "no",
    )
    await _emit_llm_progress(
        "llm_configured",
        {
            "message": f"Ready — {model_label} @ {host}",
            "model": model_label,
            "host": host,
            "llm_id": llm_id or "",
            "message_count": len(messages),
        },
    )

    if verbose:
        logger.info("LLM PROMPT\n%s", _format_messages(messages))

    working_messages: list[dict[str, Any]] = list(messages)
    last_usage: dict[str, int] | None = None
    accumulated_text: str = ""  # text from command-tool iterations, prepended to final
    half_limit = _MAX_COMMAND_TOOL_ITERATIONS // 2
    warned_at_half = False

    try:
        for iteration in range(_MAX_COMMAND_TOOL_ITERATIONS + 1):
            final: FinalPayload | None = None

            await _emit_llm_progress(
                "llm_round",
                {"message": f"LLM round {iteration + 1}…", "iteration": iteration},
            )
            async for event in _stream_once(
                working_messages,
                cfg,
                verbose,
                stop_sequences=stop_sequences,
                tools=tools,
                cancel_event=_cancel,
                enable_thinking=eff_thinking,
                round_index=iteration,
            ):
                if event.preview:
                    yield event
                elif event.final:
                    final = event.final
                    if event.final.usage:
                        last_usage = event.final.usage

            if final is None:
                logger.error(
                    "generate_stream: no final event from _stream_once (iteration=%s)",
                    iteration,
                )
                raise LLMError(
                    "LLM stream ended without a completion event (internal error)"
                )

            if final.interrupted:
                yield StreamEvent(
                    final=FinalPayload(
                        text=accumulated_text + final.text,
                        tool_calls=final.tool_calls,
                        usage=last_usage,
                        interrupted=True,
                    )
                )
                _interrupted = True
                break

            # ── Command tool path ─────────────────────────────────────────
            # Execute all command tool calls in this iteration.
            command_tcs = (
                [tc for tc in final.tool_calls if tc.name in command_tool_handlers]
                if command_tool_handlers is not None
                else []
            )
            if command_tcs:
                assert command_tool_handlers is not None
                assistant_tool_calls: list[dict[str, Any]] = []
                tool_results: list[dict[str, Any]] = []
                tool_markdowns: list[str] = []
                for tc in command_tcs:
                    handler = command_tool_handlers[tc.name]
                    result = await handler(tc.arguments, project_root)
                    if not warned_at_half and iteration + 1 >= half_limit:
                        warned_at_half = True
                        warning = (
                            f"\n\n[Warning: you have used {iteration + 1} of "
                            f"{_MAX_COMMAND_TOOL_ITERATIONS} allowed tool calls "
                            "this response.]"
                        )
                        result = result + warning
                        yield StreamEvent(preview=warning)
                    md = encode_ai_secrets(
                        _format_tool_call_markdown(
                            tc.name, tc.arguments, response_char_len=len(result),
                        )
                    )
                    yield StreamEvent(preview=md)
                    tool_markdowns.append(md)
                    assistant_tool_calls.append(
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                    )
                    tool_results.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )
                accumulated_text += final.text + "".join(tool_markdowns)
                working_messages.append(
                    {
                        "role": "assistant",
                        "content": final.text or None,
                        "tool_calls": assistant_tool_calls,
                    }
                )
                working_messages.extend(tool_results)
                continue

            # ── Normal end (no tool calls or unknown tools) ───────────────
            for tc in final.tool_calls:
                yield StreamEvent(
                    preview=encode_ai_secrets(
                        _format_tool_call_markdown(
                            tc.name, tc.arguments, response_char_len=None,
                        )
                    )
                )
            yield StreamEvent(
                final=FinalPayload(
                    text=accumulated_text + final.text,
                    tool_calls=final.tool_calls,
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
                    tool_calls=[],
                    usage=last_usage,
                    interrupted=False,
                )
            )

    finally:
        if _sigint_installed:
            loop.remove_signal_handler(signal.SIGINT)

    if _interrupted:
        raise KeyboardInterrupt
