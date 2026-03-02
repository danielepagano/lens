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
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from lens.core.annotations import encode_ai_secrets

logger = logging.getLogger(__name__)


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


def _format_messages(messages: list[dict[str, str]]) -> str:
    """Format messages as a human-readable block for logging."""
    sep = "─" * 60
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        parts.append(f"[{role}]\n{content}")
    return f"{sep}\n" + f"\n{sep}\n".join(parts) + f"\n{sep}"


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


async def generate_stream(
    messages: list[dict[str, str]],
    project_root: Path,
    *,
    llm_id: str | None = None,
    stop_sequences: list[str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """Stream LLM output as structured events: preview (HTML comments stripped)
    during generation, and a final payload with encoded text, optional tool
    call, usage, and interrupted flag.
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

    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    response_parts: list[str] = []
    chunks: list[str] = []
    usage: dict[str, int] | None = None
    mid_comment = False

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
                    if _cancel.is_set():
                        _interrupted = True
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
                    if content:
                        if verbose:
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
    finally:
        if _sigint_installed:
            loop.remove_signal_handler(signal.SIGINT)

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
                _interrupted = True
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

    if verbose and response_parts:
        sep = "─" * 60
        logger.info("LLM RESPONSE\n%s\n%s\n%s", sep, "".join(response_parts), sep)

    payload_out = FinalPayload(
        text=encoded_text,
        tool_call=tool_call,
        usage=usage,
        interrupted=_interrupted,
    )
    yield StreamEvent(final=payload_out)

    if _interrupted:
        raise KeyboardInterrupt
