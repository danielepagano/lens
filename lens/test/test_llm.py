"""Unit tests for lens.llm: config loading and streaming generation."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from lens.core.llm import LLMError, _load_config, generate  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MESSAGES: list[dict[str, str]] = [
    {"role": "system", "content": "You are a narrator."},
    {"role": "user", "content": "Write the opening line."},
]


def _collect(gen: Any) -> list[str]:
    """Exhaust an async generator and return all yielded chunks."""
    async def _inner() -> list[str]:
        return [chunk async for chunk in gen]
    return asyncio.run(_inner())


def _sse(*payloads: dict[str, Any]) -> list[str]:
    """Build SSE-formatted lines from JSON dicts, ending with [DONE]."""
    lines = [f"data: {json.dumps(p)}" for p in payloads]
    lines.append("data: [DONE]")
    return lines


def _chunk(content: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": content}}]}


def _usage_chunk(prompt: int = 10, completion: int = 5) -> dict[str, Any]:
    return {
        "choices": [{"delta": {}}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


class _FakeResponse:
    """Minimal async context manager mimicking httpx.Response in stream mode."""

    def __init__(
        self,
        status_code: int = 200,
        lines: list[str] | None = None,
        body: bytes = b"",
        raise_in_iter: BaseException | None = None,
    ) -> None:
        self.status_code = status_code
        self._lines = lines or []
        self._body = body
        self._raise_in_iter = raise_in_iter
        self.last_method: str = ""
        self.last_url: str = ""
        self.last_kwargs: dict[str, Any] = {}

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):  # type: ignore[return]
        for line in self._lines:
            if self._raise_in_iter is not None:
                raise self._raise_in_iter
            yield line

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


class _FakeClient:
    """Minimal async context manager mimicking httpx.AsyncClient."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.captured_method: str = ""
        self.captured_url: str = ""
        self.captured_kwargs: dict[str, Any] = {}

    def stream(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.captured_method = method
        self.captured_url = url
        self.captured_kwargs = kwargs
        return self._response

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


def _fake_client_cls(response: _FakeResponse):
    """Return a factory that ignores timeout and returns _FakeClient."""
    client = _FakeClient(response)

    def _factory(**_kwargs: Any) -> _FakeClient:
        return client

    return _factory, client


# ---------------------------------------------------------------------------
# _load_config tests
# ---------------------------------------------------------------------------

class TestLoadConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, content: str) -> None:
        (self.root / "lens.toml").write_text(content)

    def test_missing_lens_toml_raises(self) -> None:
        with self.assertRaises(LLMError) as ctx:
            _load_config(self.root, None)
        self.assertIn("lens.toml not found", str(ctx.exception))

    def test_no_llm_entries_raises(self) -> None:
        self._write("[project]\nnarrative = \"test\"\n")
        with self.assertRaises(LLMError) as ctx:
            _load_config(self.root, None)
        self.assertIn("no [[llm]] entries", str(ctx.exception))

    def test_uses_first_entry_by_default(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://first.example.com/v1\"\nmodel = \"first\"\n\n"
            "[[llm]]\nbase_url = \"https://second.example.com/v1\"\nmodel = \"second\"\n"
        )
        cfg, _ = _load_config(self.root, None)
        self.assertEqual(cfg.base_url, "https://first.example.com/v1")
        self.assertEqual(cfg.model, "first")

    def test_selects_entry_by_id(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://default.example.com/v1\"\n\n"
            "[[llm]]\nid = \"fast\"\nbase_url = \"https://fast.example.com/v1\"\nmodel = \"mini\"\n"
        )
        cfg, _ = _load_config(self.root, "fast")
        self.assertEqual(cfg.base_url, "https://fast.example.com/v1")
        self.assertEqual(cfg.model, "mini")

    def test_unknown_id_raises(self) -> None:
        self._write("[[llm]]\nbase_url = \"https://api.example.com/v1\"\n")
        with self.assertRaises(LLMError) as ctx:
            _load_config(self.root, "ghost")
        self.assertIn("ghost", str(ctx.exception))

    def test_missing_base_url_raises(self) -> None:
        self._write("[[llm]]\nmodel = \"gpt-4o\"\n")
        with self.assertRaises(LLMError) as ctx:
            _load_config(self.root, None)
        self.assertIn("base_url", str(ctx.exception))

    def test_api_key_env_unset_raises(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
            "api_key_env = \"_LENS_TEST_KEY_UNSET\"\n"
        )
        os.environ.pop("_LENS_TEST_KEY_UNSET", None)
        with self.assertRaises(LLMError) as ctx:
            _load_config(self.root, None)
        self.assertIn("_LENS_TEST_KEY_UNSET", str(ctx.exception))

    def test_api_key_read_from_env(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
            "api_key_env = \"_LENS_TEST_KEY\"\n"
        )
        os.environ["_LENS_TEST_KEY"] = "sk-secret"
        try:
            cfg, _ = _load_config(self.root, None)
            self.assertEqual(cfg.api_key, "sk-secret")
        finally:
            os.environ.pop("_LENS_TEST_KEY", None)

    def test_no_api_key_env_means_empty_key(self) -> None:
        self._write("[[llm]]\nbase_url = \"https://api.example.com/v1\"\n")
        cfg, _ = _load_config(self.root, None)
        self.assertEqual(cfg.api_key, "")

    def test_verbose_llm_default_false(self) -> None:
        self._write("[[llm]]\nbase_url = \"https://api.example.com/v1\"\n")
        _, verbose = _load_config(self.root, None)
        self.assertFalse(verbose)

    def test_verbose_llm_true(self) -> None:
        self._write(
            "[project]\nverbose_llm = true\n\n"
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
        )
        _, verbose = _load_config(self.root, None)
        self.assertTrue(verbose)

    def test_default_temperature_and_timeout(self) -> None:
        self._write("[[llm]]\nbase_url = \"https://api.example.com/v1\"\n")
        cfg, _ = _load_config(self.root, None)
        self.assertAlmostEqual(cfg.temperature, 0.8)
        self.assertEqual(cfg.timeout_seconds, 120)

    def test_custom_temperature_and_timeout(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
            "temperature = 0.2\ntimeout_seconds = 30\n"
        )
        cfg, _ = _load_config(self.root, None)
        self.assertAlmostEqual(cfg.temperature, 0.2)
        self.assertEqual(cfg.timeout_seconds, 30)


# ---------------------------------------------------------------------------
# generate (streaming) tests
# ---------------------------------------------------------------------------

class TestGenerate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\nmodel = \"test-model\"\n"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, response: _FakeResponse, **kwargs: Any) -> tuple[list[str], _FakeClient]:
        factory, client = _fake_client_cls(response)
        with patch("lens.core.llm.httpx.AsyncClient", factory):
            chunks = _collect(generate(MESSAGES, self.root, **kwargs))
        return chunks, client

    def test_yields_content_chunks(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("Once"), _chunk(" upon"), _chunk(" a time")))
        chunks, _ = self._run(resp)
        self.assertEqual(chunks, ["Once", " upon", " a time"])

    def test_concatenated_text_matches_expected(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("Hello"), _chunk(", "), _chunk("world!")))
        chunks, _ = self._run(resp)
        self.assertEqual("".join(chunks), "Hello, world!")

    def test_usage_chunk_logged_not_yielded(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("text"), _usage_chunk(10, 5)))
        with self.assertLogs("lens.core.llm", level="INFO") as log:
            chunks, _ = self._run(resp)
        self.assertEqual(chunks, ["text"])
        usage_logs = [m for m in log.output if "usage" in m.lower()]
        self.assertTrue(usage_logs, "expected usage to be logged")
        self.assertIn("10", usage_logs[0])
        self.assertIn("5", usage_logs[0])

    def test_stop_sequences_included_in_payload(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("ok")))
        _, client = self._run(resp, stop_sequences=["[/write]: #"])
        self.assertEqual(client.captured_kwargs.get("json", {}).get("stop"), ["[/write]: #"])

    def test_no_stop_sequences_omitted_from_payload(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("ok")))
        _, client = self._run(resp)
        self.assertNotIn("stop", client.captured_kwargs.get("json", {}))

    def test_api_key_sent_as_bearer(self) -> None:
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
            "api_key_env = \"_LENS_TEST_KEY\"\n"
        )
        os.environ["_LENS_TEST_KEY"] = "sk-test"
        try:
            resp = _FakeResponse(lines=_sse(_chunk("ok")))
            _, client = self._run(resp)
        finally:
            os.environ.pop("_LENS_TEST_KEY", None)
        self.assertEqual(
            client.captured_kwargs.get("headers", {}).get("Authorization"),
            "Bearer sk-test",
        )

    def test_non_200_raises_llm_error(self) -> None:
        resp = _FakeResponse(status_code=401, body=b'{"error": "Unauthorized"}')
        with self.assertRaises(LLMError) as ctx:
            self._run(resp)
        self.assertIn("401", str(ctx.exception))

    def test_timeout_raises_llm_error(self) -> None:
        resp = _FakeResponse(
            lines=["data: keep going"],  # non-empty so aiter_lines runs
            raise_in_iter=httpx.TimeoutException("timed out"),
        )
        with self.assertRaises(LLMError) as ctx:
            self._run(resp)
        self.assertIn("timed out", str(ctx.exception).lower())

    def test_request_error_raises_llm_error(self) -> None:
        resp = _FakeResponse(
            lines=["data: keep going"],
            raise_in_iter=httpx.RequestError("connection refused"),
        )
        with self.assertRaises(LLMError) as ctx:
            self._run(resp)
        self.assertIn("connection refused", str(ctx.exception).lower())

    def test_malformed_json_chunk_skipped(self) -> None:
        resp = _FakeResponse(
            lines=["data: not-json", f"data: {json.dumps(_chunk('ok'))}", "data: [DONE]"]
        )
        with self.assertLogs("lens.core.llm", level="WARNING") as log:
            chunks, _ = self._run(resp)
        self.assertEqual(chunks, ["ok"])
        self.assertTrue(any("could not decode" in m for m in log.output))

    def test_config_error_raised_on_first_iteration(self) -> None:
        # Calling generate() itself doesn't raise — the error surfaces on iteration.
        gen = generate(MESSAGES, self.root, llm_id="missing-id")
        with self.assertRaises(LLMError):
            asyncio.run(anext(gen))

    def test_verbose_logs_prompt_and_response(self) -> None:
        (self.root / "lens.toml").write_text(
            "[project]\nverbose_llm = true\n\n"
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
        )
        resp = _FakeResponse(lines=_sse(_chunk("narrate"), _chunk(" this")))
        with self.assertLogs("lens.core.llm", level="INFO") as log:
            self._run(resp)
        combined = "\n".join(log.output)
        self.assertIn("PROMPT", combined)
        self.assertIn("RESPONSE", combined)
        self.assertIn("narrate this", combined)


async def anext(gen: Any) -> Any:
    return await gen.__anext__()
