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

from lens.core.llm import (
    LLMError,
    FinalPayload,
    StreamEvent,
    _load_config,  # pyright: ignore[reportPrivateUsage]
    generate_stream,
    llm_progress_scope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MESSAGES: list[dict[str, str]] = [
    {"role": "system", "content": "You are a narrator."},
    {"role": "user", "content": "Write the opening line."},
]


def _collect_events(gen: Any) -> tuple[list[str], FinalPayload | None]:
    """Exhaust generate_stream and return (previews, final_payload)."""
    previews: list[str] = []
    final: FinalPayload | None = None

    async def _inner() -> tuple[list[str], FinalPayload | None]:
        nonlocal final
        async for event in gen:
            if event.preview:
                previews.append(event.preview)
            if event.final:
                final = event.final
                break
        return (previews, final)

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
        delay_first_line_s: float = 0.0,
        delay_mid_line_s: float = 0.0,
    ) -> None:
        self.status_code = status_code
        self._lines = lines or []
        self._body = body
        self._raise_in_iter = raise_in_iter
        self._delay_first_line_s = delay_first_line_s
        self._delay_mid_line_s = delay_mid_line_s
        self.last_method: str = ""
        self.last_url: str = ""
        self.last_kwargs: dict[str, Any] = {}

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):  # type: ignore[return]
        for i, line in enumerate(self._lines):
            if i == 0 and self._delay_first_line_s > 0:
                await asyncio.sleep(self._delay_first_line_s)
            elif i > 0 and self._delay_mid_line_s > 0:
                await asyncio.sleep(self._delay_mid_line_s)
            if self._raise_in_iter is not None:
                raise self._raise_in_iter
            yield line

    async def aclose(self) -> None:
        pass

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

    def build_request(self, method: str, url: str, **kwargs: Any) -> object:
        self.captured_method = method
        self.captured_url = url
        self.captured_kwargs = kwargs
        return object()

    async def send(self, _request: object, *, stream: bool = False) -> _FakeResponse:
        _ = stream
        return self._response

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


class _SequentialFakeClient:
    """Returns a different fake response on each ``send`` call."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self._index = 0
        self.captured_method: str = ""
        self.captured_url: str = ""
        self.captured_kwargs: dict[str, Any] = {}
        self.send_count = 0

    def build_request(self, method: str, url: str, **kwargs: Any) -> object:
        self.captured_method = method
        self.captured_url = url
        self.captured_kwargs = kwargs
        return object()

    async def send(self, _request: object, *, stream: bool = False) -> _FakeResponse:
        _ = stream
        self.send_count += 1
        idx = min(self._index, len(self._responses) - 1)
        self._index += 1
        return self._responses[idx]

    async def __aenter__(self) -> _SequentialFakeClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass


def _fake_client_cls(response: _FakeResponse):
    """Return a factory that ignores timeout and returns _FakeClient."""
    client = _FakeClient(response)

    def _factory(**_kwargs: Any) -> _FakeClient:
        return client

    return _factory, client


def _sequential_client_factory(responses: list[_FakeResponse]):
    client = _SequentialFakeClient(responses)

    def _factory(**_kwargs: Any) -> _SequentialFakeClient:
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
        self.assertAlmostEqual(cfg.first_token_timeout_seconds, 10.0)
        self.assertAlmostEqual(cfg.timeout_seconds, 120.0)

    def test_custom_temperature_and_timeout(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
            "temperature = 0.2\ntimeout_seconds = 30\n"
        )
        cfg, _ = _load_config(self.root, None)
        self.assertAlmostEqual(cfg.temperature, 0.2)
        self.assertAlmostEqual(cfg.timeout_seconds, 30.0)

    def test_custom_first_token_timeout(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
            "first_token_timeout_seconds = 90\n"
        )
        cfg, _ = _load_config(self.root, None)
        self.assertAlmostEqual(cfg.first_token_timeout_seconds, 90.0)

    # ------------------------------------------------------------------
    # Per-operator [operator.<name>] overrides
    # ------------------------------------------------------------------

    def test_operator_section_overrides_temperature(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\ntemperature = 0.8\n\n"
            "[operator.write]\ntemperature = 0.2\n"
        )
        cfg, _ = _load_config(self.root, None, operator_name="write")
        self.assertAlmostEqual(cfg.temperature, 0.2)

    def test_operator_section_overrides_timeouts(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[operator.play]\ntimeout_seconds = 300\nfirst_token_timeout_seconds = 25\n"
        )
        cfg, _ = _load_config(self.root, None, operator_name="play")
        self.assertAlmostEqual(cfg.timeout_seconds, 300.0)
        self.assertAlmostEqual(cfg.first_token_timeout_seconds, 25.0)

    def test_operator_section_overrides_reasoning_effort(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[operator.design]\nreasoning_effort = \"high\"\n"
        )
        cfg, _ = _load_config(self.root, None, operator_name="design")
        self.assertEqual(cfg.reasoning_effort, "high")

    def test_operator_section_enables_thinking(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[operator.write]\nreasoning = true\n"
        )
        cfg, _ = _load_config(self.root, None, operator_name="write")
        self.assertTrue(cfg.enable_thinking)

    def test_operator_section_disables_thinking(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\nreasoning = true\n\n"
            "[operator.play]\nreasoning = false\n"
        )
        cfg, _ = _load_config(self.root, None, operator_name="play")
        self.assertFalse(cfg.enable_thinking)

    def test_operator_section_selects_llm_id(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://default.example.com/v1\"\nmodel = \"default\"\n\n"
            "[[llm]]\nid = \"fast\"\nbase_url = \"https://fast.example.com/v1\"\nmodel = \"mini\"\n\n"
            "[operator.write]\nllm = \"fast\"\n"
        )
        cfg, _ = _load_config(self.root, None, operator_name="write")
        self.assertEqual(cfg.base_url, "https://fast.example.com/v1")
        self.assertEqual(cfg.model, "mini")

    def test_explicit_llm_id_overrides_operator_default(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://default.example.com/v1\"\nmodel = \"default\"\n\n"
            "[[llm]]\nid = \"fast\"\nbase_url = \"https://fast.example.com/v1\"\nmodel = \"mini\"\n\n"
            "[[llm]]\nid = \"smart\"\nbase_url = \"https://smart.example.com/v1\"\nmodel = \"big\"\n\n"
            "[operator.write]\nllm = \"fast\"\n"
        )
        # CLI-supplied llm_id="smart" must win over operator default "fast"
        cfg, _ = _load_config(self.root, "smart", operator_name="write")
        self.assertEqual(cfg.model, "big")

    def test_operator_override_takes_precedence_over_llm_entry(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\ntemperature = 0.5\n\n"
            "[operator.write]\ntemperature = 0.1\n"
        )
        cfg, _ = _load_config(self.root, None, operator_name="write")
        self.assertAlmostEqual(cfg.temperature, 0.1)

    def test_no_operator_section_uses_llm_entry_values(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\ntemperature = 0.3\n"
        )
        cfg, _ = _load_config(self.root, None, operator_name="write")
        self.assertAlmostEqual(cfg.temperature, 0.3)

    def test_unknown_operator_name_falls_through_to_defaults(self) -> None:
        self._write("[[llm]]\nbase_url = \"https://api.example.com/v1\"\n")
        cfg, _ = _load_config(self.root, None, operator_name="nonexistent")
        self.assertAlmostEqual(cfg.temperature, 0.8)
        self.assertFalse(cfg.enable_thinking)

    def test_extra_headers_parsed(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[llm.extra_headers]\n"
            "HTTP-Referer = \"https://example.com\"\n"
            "X-Custom = \"my-app\"\n"
        )
        cfg, _ = _load_config(self.root, None)
        self.assertEqual(
            cfg.extra_headers,
            {"HTTP-Referer": "https://example.com", "X-Custom": "my-app"},
        )

    def test_extra_payload_inline_table(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[llm.extra_payload]\n"
            "routing = { sort = \"throughput\", allow_fallbacks = false }\n"
        )
        cfg, _ = _load_config(self.root, None)
        self.assertEqual(
            cfg.extra_payload,
            {"routing": {"sort": "throughput", "allow_fallbacks": False}},
        )

    def test_extra_payload_yaml_string(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[llm.extra_payload]\n"
            "routing = '''\n"
            "sort: throughput\n"
            "order: [a, b]\n"
            "'''\n"
        )
        cfg, _ = _load_config(self.root, None)
        self.assertEqual(
            cfg.extra_payload,
            {"routing": {"sort": "throughput", "order": ["a", "b"]}},
        )

    def test_extra_payload_json_string(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            '[llm.extra_payload]\n'
            'flags = "{\\"enabled\\": true}"\n'
        )
        cfg, _ = _load_config(self.root, None)
        self.assertEqual(cfg.extra_payload, {"flags": {"enabled": True}})

    def test_extra_payload_invalid_string_raises(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[llm.extra_payload]\n"
            "bad = \"not: valid: yaml: [[\"\n"
        )
        with self.assertRaises(LLMError) as ctx:
            _load_config(self.root, None)
        self.assertIn("bad", str(ctx.exception))

    def test_extra_headers_non_string_value_raises(self) -> None:
        self._write(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[llm.extra_headers]\n"
            "X-Bad = 42\n"
        )
        with self.assertRaises(LLMError) as ctx:
            _load_config(self.root, None)
        self.assertIn("extra_headers", str(ctx.exception))

    def test_extra_headers_and_payload_default_empty(self) -> None:
        self._write("[[llm]]\nbase_url = \"https://api.example.com/v1\"\n")
        cfg, _ = _load_config(self.root, None)
        self.assertEqual(cfg.extra_headers, {})
        self.assertEqual(cfg.extra_payload, {})


# ---------------------------------------------------------------------------
# generate (streaming) tests
# ---------------------------------------------------------------------------

class TestGenerateStream(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\nmodel = \"test-model\"\n"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(
        self, response: _FakeResponse, **kwargs: Any
    ) -> tuple[list[str], FinalPayload | None, _FakeClient]:
        factory, client = _fake_client_cls(response)
        with patch("lens.core.llm.httpx.AsyncClient", factory):
            previews, final = _collect_events(
                generate_stream(MESSAGES, self.root, **kwargs)
            )
        return previews, final, client

    def _run_sequential(
        self, responses: list[_FakeResponse], **kwargs: Any
    ) -> tuple[list[str], FinalPayload | None, _SequentialFakeClient]:
        factory, client = _sequential_client_factory(responses)
        with patch("lens.core.llm.httpx.AsyncClient", factory):
            previews, final = _collect_events(
                generate_stream(MESSAGES, self.root, **kwargs)
            )
        return previews, final, client

    def test_yields_previews_then_final(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("Once"), _chunk(" upon"), _chunk(" a time")))
        previews, final, _ = self._run(resp)
        self.assertIsNotNone(final)
        assert final is not None
        self.assertEqual(final.text, "Once upon a time")
        self.assertEqual("".join(previews), "Once upon a time")

    def test_concatenated_text_matches_expected(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("Hello"), _chunk(", "), _chunk("world!")))
        previews, final, _ = self._run(resp)
        self.assertIsNotNone(final)
        assert final is not None
        self.assertEqual(final.text, "Hello, world!")
        self.assertEqual("".join(previews), "Hello, world!")

    def test_ai_secret_blocks_encoded_in_final(self) -> None:
        resp = _FakeResponse(
            lines=_sse(
                _chunk("Text with "),
                _chunk("<!-- ai:secret:\n"),
                _chunk("player secret\n"),
                _chunk("--> more."),
            )
        )
        previews, final, _ = self._run(resp)
        self.assertIsNotNone(final)
        assert final is not None
        full = final.text
        self.assertIn("<!-- ai:secret:", full)
        self.assertIn("cynlre frperg", full)
        self.assertNotIn("player secret", full)
        self.assertEqual("".join(previews), "Text with  more.")

    def test_usage_chunk_logged_not_in_previews(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("text"), _usage_chunk(10, 5)))
        with self.assertLogs("lens.core.llm", level="INFO") as log:
            previews, final, _ = self._run(resp)
        self.assertEqual("".join(previews), "text")
        self.assertIsNotNone(final)
        assert final is not None
        self.assertEqual(final.text, "text")
        usage_logs = [m for m in log.output if "usage" in m.lower()]
        self.assertTrue(usage_logs, "expected usage to be logged")
        self.assertIn("10", usage_logs[0])
        self.assertIn("5", usage_logs[0])

    def test_stop_sequences_included_in_payload(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("ok")))
        _, _, client = self._run(resp, stop_sequences=["[/write]: #"])
        self.assertEqual(client.captured_kwargs.get("json", {}).get("stop"), ["[/write]: #"])

    def test_no_stop_sequences_omitted_from_payload(self) -> None:
        resp = _FakeResponse(lines=_sse(_chunk("ok")))
        _, _, client = self._run(resp)
        self.assertNotIn("stop", client.captured_kwargs.get("json", {}))

    def test_api_key_sent_as_bearer(self) -> None:
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
            "api_key_env = \"_LENS_TEST_KEY\"\n"
        )
        os.environ["_LENS_TEST_KEY"] = "sk-test"
        try:
            resp = _FakeResponse(lines=_sse(_chunk("ok")))
            _, _, client = self._run(resp)
        finally:
            os.environ.pop("_LENS_TEST_KEY", None)
        self.assertEqual(
            client.captured_kwargs.get("headers", {}).get("Authorization"),
            "Bearer sk-test",
        )

    def test_extra_headers_and_payload_in_request(self) -> None:
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n\n"
            "[llm.extra_headers]\n"
            "X-Custom = \"my-app\"\n\n"
            "[llm.extra_payload]\n"
            "routing = { sort = \"price\" }\n"
        )
        resp = _FakeResponse(lines=_sse(_chunk("ok")))
        _, _, client = self._run(resp)
        headers = client.captured_kwargs.get("headers", {})
        self.assertEqual(headers.get("X-Custom"), "my-app")
        self.assertEqual(headers.get("Accept"), "text/event-stream")
        body = client.captured_kwargs.get("json", {})
        self.assertEqual(body.get("routing"), {"sort": "price"})

    def test_authorization_overrides_extra_headers(self) -> None:
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
            "api_key_env = \"_LENS_TEST_KEY\"\n\n"
            "[llm.extra_headers]\n"
            "Authorization = \"Bearer wrong\"\n"
        )
        os.environ["_LENS_TEST_KEY"] = "sk-real"
        try:
            resp = _FakeResponse(lines=_sse(_chunk("ok")))
            _, _, client = self._run(resp)
        finally:
            os.environ.pop("_LENS_TEST_KEY", None)
        self.assertEqual(
            client.captured_kwargs.get("headers", {}).get("Authorization"),
            "Bearer sk-real",
        )

    def test_non_200_raises_llm_error(self) -> None:
        resp = _FakeResponse(status_code=401, body=b'{"error": "Unauthorized"}')
        with self.assertRaises(LLMError) as ctx:
            self._run(resp)
        self.assertIn("401", str(ctx.exception))

    def test_retries_transient_http_error(self) -> None:
        fail = _FakeResponse(status_code=502, body=b'{"error": "Bad gateway"}')
        ok = _FakeResponse(lines=_sse(_chunk("recovered")))
        previews, final, client = self._run_sequential([fail, ok])
        self.assertEqual(client.send_count, 2)
        self.assertIsNotNone(final)
        assert final is not None
        self.assertEqual(final.text, "recovered")
        self.assertEqual("".join(previews), "recovered")

    def test_retries_empty_response(self) -> None:
        empty = _FakeResponse(lines=_sse())
        ok = _FakeResponse(lines=_sse(_chunk("after retry")))
        _previews, final, client = self._run_sequential([empty, ok])
        self.assertEqual(client.send_count, 2)
        self.assertIsNotNone(final)
        assert final is not None
        self.assertEqual(final.text, "after retry")

    def test_does_not_retry_auth_error(self) -> None:
        fail = _FakeResponse(status_code=401, body=b'{"error": "Unauthorized"}')
        ok = _FakeResponse(lines=_sse(_chunk("should not run")))
        with self.assertRaises(LLMError) as ctx:
            self._run_sequential([fail, ok])
        self.assertIn("401", str(ctx.exception))

    def test_request_error_retries_once(self) -> None:
        fail = _FakeResponse(
            lines=["data: keep going"],
            raise_in_iter=httpx.RequestError("connection refused"),
        )
        ok = _FakeResponse(lines=_sse(_chunk("back online")))
        _previews, final, client = self._run_sequential([fail, ok])
        self.assertEqual(client.send_count, 2)
        self.assertIsNotNone(final)
        assert final is not None
        self.assertEqual(final.text, "back online")

    def test_timeout_raises_llm_error(self) -> None:
        resp = _FakeResponse(
            lines=["data: keep going"],  # non-empty so aiter_lines runs
            raise_in_iter=httpx.TimeoutException("timed out"),
        )
        with self.assertRaises(LLMError) as ctx:
            self._run(resp)
        self.assertIn("timed out", str(ctx.exception).lower())

    def test_first_token_timeout_sse_delayed(self) -> None:
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\nmodel = \"m\"\n"
            "first_token_timeout_seconds = 0.05\n"
        )
        resp = _FakeResponse(
            lines=_sse(_chunk("slow")),
            delay_first_line_s=0.2,
        )
        with self.assertRaises(LLMError) as ctx:
            self._run(resp)
        self.assertIn("first_token", str(ctx.exception).lower())

    def test_stream_idle_timeout_between_chunks(self) -> None:
        (self.root / "lens.toml").write_text(
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\nmodel = \"m\"\n"
            "timeout_seconds = 0.05\n"
        )
        resp = _FakeResponse(
            lines=_sse(_chunk("a"), _chunk("b")),
            delay_mid_line_s=0.3,
        )
        with self.assertRaises(LLMError) as ctx:
            self._run(resp)
        self.assertIn("stalled", str(ctx.exception).lower())

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
            _, final, _ = self._run(resp)
        self.assertIsNotNone(final)
        self.assertEqual(final.text if final else "", "ok")
        self.assertTrue(any("could not decode" in m for m in log.output))

    def test_config_error_raised_on_first_iteration(self) -> None:
        gen = generate_stream(MESSAGES, self.root, llm_id="missing-id")
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

    def test_reasoning_content_verbose_only_not_in_final_text(self) -> None:
        """reasoning_content is verbose-logged per delta; main content is final.text only."""
        (self.root / "lens.toml").write_text(
            "[project]\nverbose_llm = true\n\n"
            "[[llm]]\nbase_url = \"https://api.example.com/v1\"\n"
        )
        thinking_chunk = {"choices": [{"delta": {"reasoning_content": "think think"}}]}
        resp = _FakeResponse(lines=_sse(thinking_chunk, _chunk("answer")))
        with self.assertLogs("lens.core.llm", level="INFO") as log:
            _, final, _ = self._run(resp)
        combined = "\n".join(log.output)
        self.assertIn("LLM REASONING", combined)
        self.assertIn("think think", combined)
        assert final is not None
        self.assertEqual(final.text, "answer")
        self.assertNotIn("think think", final.text)

    def test_command_tool_text_accumulated_into_final(self) -> None:
        """Text emitted before a command tool call must appear in final.text."""
        import asyncio as _asyncio

        tc = {
            "index": 0,
            "id": "call_ct1",
            "function": {"name": "kb_get", "arguments": '{"id":"npc.villain"}'},
        }
        iter1 = {
            "choices": [{"delta": {"content": "Before.", "tool_calls": [tc]}}]
        }
        iter2_lines = _sse(_chunk("After."))

        call_count = 0

        class _TwoPhaseResponse:
            status_code = 200

            async def aread(self) -> bytes:
                return b""

            async def aiter_lines(self):  # type: ignore[return]
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    yield f"data: {json.dumps(iter1)}"
                    yield "data: [DONE]"
                else:
                    for line in iter2_lines:
                        yield line

            async def __aenter__(self) -> _TwoPhaseResponse:
                return self

            async def __aexit__(self, *_: Any) -> None:
                pass

            async def aclose(self) -> None:
                pass

        class _TwoPhaseClient:
            def build_request(self, _m: str, _u: str, **_kw: Any) -> object:
                return object()

            async def send(self, _req: object, *, stream: bool = False) -> _TwoPhaseResponse:
                _ = stream
                return _TwoPhaseResponse()

            async def __aenter__(self) -> _TwoPhaseClient:
                return self

            async def __aexit__(self, *_: Any) -> None:
                pass

        async def _handler(args: dict[str, Any], _root: Any) -> str:
            return "kb content"

        async def _inner() -> tuple[list[str], FinalPayload | None]:
            previews: list[str] = []
            final: FinalPayload | None = None
            async for event in generate_stream(
                MESSAGES,
                self.root,
                command_tool_handlers={"kb_get": _handler},
            ):
                if event.preview:
                    previews.append(event.preview)
                if event.final:
                    final = event.final
            return previews, final

        def _make_client(**_kw: Any) -> _TwoPhaseClient:
            return _TwoPhaseClient()

        with patch("lens.core.llm.httpx.AsyncClient", _make_client):
            previews, final = _asyncio.run(_inner())

        assert final is not None
        self.assertIn("Before.", previews)
        self.assertIn("Before.", final.text)
        self.assertIn("After.", final.text)
        self.assertIn("```tool-call", final.text)
        self.assertIn("kb_get", final.text)
        self.assertIn("10 bytes", final.text)  # len("kb content")
        self.assertTrue(any("```tool-call" in p for p in previews))

    def test_structured_design_yields_tool_event(self) -> None:
        """With STRUCTURED policy (design), command-tool calls yield tool_event not preview fences."""
        import asyncio as _asyncio

        tc = {
            "index": 0,
            "id": "call_ct1",
            "function": {"name": "kb_get", "arguments": '{"id":"npc.villain"}'},
        }
        iter1 = {
            "choices": [{"delta": {"content": "", "tool_calls": [tc]}}]
        }
        iter2_lines = _sse(_chunk("After."))

        call_count = 0

        class _TwoPhaseResponse:
            status_code = 200

            async def aread(self) -> bytes:
                return b""

            async def aiter_lines(self):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    yield f"data: {json.dumps(iter1)}"
                    yield "data: [DONE]"
                else:
                    for line in iter2_lines:
                        yield line

            async def __aenter__(self) -> _TwoPhaseResponse:
                return self

            async def __aexit__(self, *_: Any) -> None:
                pass

            async def aclose(self) -> None:
                pass

        class _TwoPhaseClient:
            def build_request(self, _m: str, _u: str, **_kw: Any) -> object:
                return object()

            async def send(self, _req: object, *, stream: bool = False) -> _TwoPhaseResponse:
                _ = stream
                return _TwoPhaseResponse()

            async def __aenter__(self) -> _TwoPhaseClient:
                return self

            async def __aexit__(self, *_: Any) -> None:
                pass

        async def _handler(args: dict[str, Any], _root: Any) -> str:
            return "kb content"

        events: list[StreamEvent] = []

        async def _inner() -> FinalPayload | None:
            final: FinalPayload | None = None
            async for event in generate_stream(
                MESSAGES,
                self.root,
                command_tool_handlers={"kb_get": _handler},
                operator_name="design",
            ):
                events.append(event)
                if event.final:
                    final = event.final
            return final

        def _make_client(**_kw: Any) -> _TwoPhaseClient:
            return _TwoPhaseClient()

        with patch("lens.core.llm.httpx.AsyncClient", _make_client):
            final = _asyncio.run(_inner())

        assert final is not None

        # --- Positive: tool_event is yielded for the tool-call segment ---
        tool_events = [e for e in events if e.tool_event is not None]
        self.assertGreater(len(tool_events), 0, "expected at least one tool_event")
        te = tool_events[0].tool_event
        assert te is not None
        self.assertEqual(te["name"], "kb_get")

        # --- Negative: no tool-call fences in the preview stream ---
        preview_fences = [e.preview for e in events if e.preview and "```tool-call" in e.preview]
        self.assertEqual(
            len(preview_fences), 0,
            "STRUCTURED policy must NOT emit tool-call fences on the preview path",
        )

        # --- Persist unchanged: artifacts still contain tool-call segments ---
        seg_texts = [seg.text for seg in final.artifacts.segments if seg.kind == "tool_call"]
        self.assertGreater(len(seg_texts), 0)
        combined = "".join(seg_texts)
        self.assertIn("```tool-call", combined, "persist artifacts must retain tool-call fences")
        self.assertIn("kb_get", combined, "persist artifacts must retain tool name")
        self.assertIn("10 bytes", combined, "persist artifacts must retain response size")

    def test_normal_end_persists_tool_call_segments(self) -> None:
        """Native tool calls (no command handlers) must persist tool-call fences in artifacts."""
        tc = {
            "index": 0,
            "id": "call_native_1",
            "function": {"name": "compress_collate", "arguments": '{"target": "ch1"}'},
        }
        chunk = {
            "choices": [
                {
                    "delta": {"tool_calls": [tc]},
                    "finish_reason": "tool_calls",
                }
            ]
        }
        resp = _FakeResponse(lines=[
            f"data: {json.dumps(chunk)}",
            "data: [DONE]",
        ])
        # No command_tool_handlers → all tool calls hit the normal-end branch.
        previews, final, _ = self._run(resp, operator_name="compress")
        self.assertIsNotNone(final)
        assert final is not None
        # Verify tool-call segment was persisted in artifacts.
        tool_segs = [s for s in final.artifacts.segments if s.kind == "tool_call"]
        self.assertGreater(len(tool_segs), 0, "expected at least one tool_call segment")
        combined = "".join(s.text for s in tool_segs)
        self.assertIn("```tool-call", combined)
        self.assertIn("compress_collate", combined)
        self.assertIn("target", combined)
        # Verify stream preview: INTERLEAVE (compress) yields raw fence.
        self.assertTrue(
            any("```tool-call" in p for p in previews),
            "INTERLEAVE policy should emit tool-call fences as previews",
        )

    def test_multiple_tool_calls_all_returned(self) -> None:
        """When LLM returns multiple tool calls, all are returned in order."""
        tc_kb1 = {
            "index": 0,
            "id": "call_1",
            "function": {"name": "kb_get", "arguments": '{"id":"npc.bob"}'},
        }
        tc_kb2 = {
            "index": 1,
            "id": "call_2",
            "function": {"name": "kb_get", "arguments": '{"id":"loc.tavern"}'},
        }
        chunk = {
            "choices": [
                {
                    "delta": {"tool_calls": [tc_kb1, tc_kb2]},
                    "finish_reason": "tool_calls",
                }
            ]
        }
        lines = [f"data: {json.dumps(chunk)}", "data: [DONE]"]
        resp = _FakeResponse(lines=lines)
        _, final, _ = self._run(resp)
        self.assertIsNotNone(final)
        assert final is not None
        self.assertEqual(len(final.tool_calls), 2)
        self.assertEqual(final.tool_calls[0].name, "kb_get")
        self.assertEqual(final.tool_calls[0].arguments, {"id": "npc.bob"})
        self.assertEqual(final.tool_calls[1].name, "kb_get")
        self.assertEqual(final.tool_calls[1].arguments, {"id": "loc.tavern"})

    def _run_with_progress(
        self, response: _FakeResponse, **kwargs: Any
    ) -> list[tuple[str, dict[str, Any]]]:
        """Exhaust generate_stream with a progress hook bound, returning captured (phase, detail)."""
        events: list[tuple[str, dict[str, Any]]] = []

        async def _capture(phase: str, detail: dict[str, Any]) -> None:
            events.append((phase, detail))

        factory, _ = _fake_client_cls(response)

        async def _inner() -> None:
            async with llm_progress_scope(_capture):
                async for _event in generate_stream(MESSAGES, self.root, **kwargs):
                    pass

        with patch("lens.core.llm.httpx.AsyncClient", factory):
            asyncio.run(_inner())
        return events

    def test_llm_stream_progress_heartbeat_for_tool_call_only_round(self) -> None:
        """A tool-call-only round (no content) still gets a bytes heartbeat for the UI."""
        args = '{"id":"npc.bob"}'
        tc = {"index": 0, "id": "call_1", "function": {"name": "kb_get", "arguments": args}}
        resp = _FakeResponse(
            lines=_sse({"choices": [{"delta": {"tool_calls": [tc]}, "finish_reason": "tool_calls"}]})
        )
        events = self._run_with_progress(resp)
        heartbeats = [detail for phase, detail in events if phase == "llm_stream_progress"]
        self.assertEqual(len(heartbeats), 1)
        self.assertEqual(heartbeats[0]["round"], 0)
        self.assertEqual(heartbeats[0]["hidden_bytes_delta"], len(args.encode("utf-8")))

    def test_llm_stream_progress_heartbeat_for_reasoning(self) -> None:
        """Reasoning-only deltas (no visible content) also get a bytes heartbeat."""
        reasoning = "thinking about the plan"
        resp = _FakeResponse(
            lines=_sse({"choices": [{"delta": {"reasoning_content": reasoning}}]}, _chunk("answer"))
        )
        events = self._run_with_progress(resp)
        heartbeats = [detail for phase, detail in events if phase == "llm_stream_progress"]
        self.assertEqual(len(heartbeats), 1)
        self.assertEqual(heartbeats[0]["hidden_bytes_delta"], len(reasoning.encode("utf-8")))

    def test_llm_stream_progress_not_emitted_for_content_only_round(self) -> None:
        """Visible content already streams as `token` events — no double counting via progress."""
        resp = _FakeResponse(lines=_sse(_chunk("Once"), _chunk(" upon a time")))
        events = self._run_with_progress(resp)
        phases = [phase for phase, _detail in events]
        self.assertNotIn("llm_stream_progress", phases)


class CommandToolProjectRootTests(unittest.TestCase):
    """Handlers must use the LLM's project_root; server process CWD is unrelated."""

    def test_kb_get_uses_passed_root_not_cwd(self) -> None:
        from lens.core.command_tools import get_command_registry

        with tempfile.TemporaryDirectory() as td_proj, tempfile.TemporaryDirectory() as td_cwd:
            proj = Path(td_proj)
            (proj / "lens.toml").write_text("[project]\n", encoding="utf-8")
            (proj / "knowledge" / "npc").mkdir(parents=True)
            (proj / "knowledge" / "npc" / "foo.md").write_text(
                "---\n---\n\nhello world", encoding="utf-8"
            )
            registry = get_command_registry(proj)
            handler = registry["kb_get"][1]
            old = os.getcwd()
            try:
                os.chdir(td_cwd)

                async def _call() -> str:
                    return await handler({"ids": ["npc.foo"]}, proj)

                out = asyncio.run(_call())
            finally:
                os.chdir(old)
            self.assertIn("npc.foo", out)
            self.assertIn("hello world", out)

    def test_kb_list_tags_uses_passed_root_not_cwd(self) -> None:
        from lens.core.command_tools import get_command_registry

        with tempfile.TemporaryDirectory() as td_proj, tempfile.TemporaryDirectory() as td_cwd:
            proj = Path(td_proj)
            (proj / "lens.toml").write_text("[project]\n", encoding="utf-8")
            (proj / "knowledge").mkdir(parents=True)
            registry = get_command_registry(proj)
            handler = registry["kb_list_tags"][1]
            old = os.getcwd()
            try:
                os.chdir(td_cwd)

                async def _call() -> str:
                    return await handler({}, proj)

                out = asyncio.run(_call())
            finally:
                os.chdir(old)
            self.assertEqual(out, "(no tags found)")


async def anext(gen: Any) -> Any:
    return await gen.__anext__()
