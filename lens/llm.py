"""LLM text generation via streaming chat completions.

Configuration is read from the project's ``lens.toml``. Add one or more
``[[llm]]`` entries; the first one is used by default unless a specific
``id`` is requested.
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

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
) -> AsyncGenerator[str, None]:
    """Stream text from the configured LLM, yielding content chunks.

    Uses the first ``[[llm]]`` entry in ``lens.toml`` unless *llm_id* selects
    a named entry. Raises ``LLMError`` on misconfiguration or API failure.

    Usage::

        async for chunk in generate(messages, project_root):
            print(chunk, end="", flush=True)
    """
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

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raise LLMError(
                        f"LLM API returned HTTP {response.status_code}: {body.decode()}"
                    )

                async for line in response.aiter_lines():
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
                            yield content

    except httpx.TimeoutException as exc:
        raise LLMError(
            f"LLM request timed out after {cfg.timeout_seconds}s"
        ) from exc
    except httpx.RequestError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    if verbose and response_parts:
        sep = "─" * 60
        logger.info("LLM RESPONSE\n%s\n%s\n%s", sep, "".join(response_parts), sep)
