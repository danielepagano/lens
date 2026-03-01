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

    verbose_llm: bool = bool(config.get("project", {}).get("verbose_llm", False))

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
class GenerateResult:
    text: str
    tool_call: ToolCall | None
    interrupted: bool


def _format_messages(messages: list[dict[str, str]]) -> str:
    """Format messages as a human-readable block for logging."""
    sep = "─" * 60
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        parts.append(f"[{role}]\n{content}")
    return f"{sep}\n" + f"\n{sep}\n".join(parts) + f"\n{sep}"


async def generate(
    messages: list[dict[str, str]],
    project_root: Path,
    *,
    llm_id: str | None = None,
    stop_sequences: list[str] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> AsyncGenerator[str, None]:
    """Stream text from the configured LLM, yielding content chunks.

    Uses the first ``[[llm]]`` entry in ``lens.toml`` unless *llm_id* selects
    a named entry. Raises ``LLMError`` on misconfiguration or API failure.

    Pass an ``asyncio.Event`` as *cancel_event* to abort the stream early.
    Setting the event causes the loop to break and the underlying HTTP
    connection to close, telling the server to stop generating.

    Usage::

        async for chunk in generate(messages, project_root):
            print(chunk, end="", flush=True)
    """
    # Always have a concrete event to check inside the loop.
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
        # Windows, or called from a non-main thread — skip SIGINT wiring.
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

    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    response_parts: list[str] = []
    chunks: list[str] = []

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
                        usage: dict[str, Any] = data["usage"]
                        logger.info(
                            "LLM usage — prompt: %s tokens, completion: %s tokens, total: %s tokens",
                            usage.get("prompt_tokens", "?"),
                            usage.get("completion_tokens", "?"),
                            usage.get("total_tokens", "?"),
                        )

                    choices: list[Any] = data.get("choices") or []
                    if choices:
                        content: str | None = choices[0].get("delta", {}).get("content")
                        if content:
                            if verbose:
                                response_parts.append(content)
                            chunks.append(content)

    except httpx.TimeoutException as exc:
        raise LLMError(
            f"LLM request timed out after {cfg.timeout_seconds}s"
        ) from exc
    except httpx.RequestError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    finally:
        if _sigint_installed:
            loop.remove_signal_handler(signal.SIGINT)

    # TODO: this makes streaming pointless
    full_text = "".join(chunks)
    yield encode_ai_secrets(full_text)

    if verbose and response_parts:
        sep = "─" * 60
        logger.info("LLM RESPONSE\n%s\n%s\n%s", sep, "".join(response_parts), sep)

    # Re-raise so CLI callers still see a normal ^C after the connection closes.
    if _interrupted:
        raise KeyboardInterrupt


async def generate_with_tools(
    messages: list[dict[str, str]],
    project_root: Path,
    *,
    llm_id: str | None = None,
    tools: list[dict[str, Any]],
    on_token: Callable[[str], Awaitable[None]] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> GenerateResult:
    """Stream text + optional tool call from the LLM, returning a GenerateResult.

    Adds ``tools`` and ``tool_choice: "auto"`` to the payload. Text chunks and
    tool call fragments are accumulated separately from the stream. Raises
    ``LLMError`` on misconfiguration or API failure.
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
        "tools": tools,
        "tool_choice": "auto",
    }
    if cfg.model:
        payload["model"] = cfg.model

    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    text_chunks: list[str] = []
    tool_id = ""
    tool_name = ""
    tool_args_fragments: list[str] = []
    got_tool_call = False

    # TODO: this streaming is pointless because we don't yield
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
                        usage: dict[str, Any] = data["usage"]
                        logger.info(
                            "LLM usage — prompt: %s tokens, completion: %s tokens, total: %s tokens",
                            usage.get("prompt_tokens", "?"),
                            usage.get("completion_tokens", "?"),
                            usage.get("total_tokens", "?"),
                        )

                    choices: list[Any] = data.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason")

                    # Text content
                    content: str | None = delta.get("content")
                    if content:
                        if on_token:
                            await on_token(content)
                        text_chunks.append(content)

                    # Tool call fragments
                    tc_list: list[Any] = delta.get("tool_calls") or []
                    if tc_list:
                        tc = tc_list[0]
                        if tc.get("id"):
                            tool_id = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            tool_name = fn["name"]
                        if fn.get("arguments"):
                            tool_args_fragments.append(fn["arguments"])

                    if finish_reason == "tool_calls":
                        got_tool_call = True

    except httpx.TimeoutException as exc:
        raise LLMError(f"LLM request timed out after {cfg.timeout_seconds}s") from exc
    except httpx.RequestError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    finally:
        if _sigint_installed:
            loop.remove_signal_handler(signal.SIGINT)

    if _interrupted:
        raise KeyboardInterrupt

    tool_call: ToolCall | None = None
    if got_tool_call and tool_name:
        raw_args = "".join(tool_args_fragments)
        try:
            parsed_args: dict[str, Any] = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            parsed_args = {}
        tool_call = ToolCall(id=tool_id, name=tool_name, arguments=parsed_args)

    text = encode_ai_secrets("".join(text_chunks))
    return GenerateResult(
        text=text,
        tool_call=tool_call,
        interrupted=False,
    )
