"""Tests for mock LLM stream directives (tokens=, tps=)."""

from __future__ import annotations

import json
import time
import urllib.request
from unittest import TestCase

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.stream_controls import (
    lorem_token_text,
    merge_stream_controls,
    parse_stream_controls,
)


class TestParseStreamControls(TestCase):
    def test_parse_tokens_and_tps(self) -> None:
        c = parse_stream_controls("please tokens=12 tps=6 finish")
        assert c is not None
        assert c.tokens == 12
        assert c.tps == 6.0

    def test_parse_tokens_only(self) -> None:
        c = parse_stream_controls("tokens=3")
        assert c is not None
        assert c.tokens == 3
        assert c.tps is None

    def test_merge_defaults(self) -> None:
        c = merge_stream_controls("hello", default_tokens=40, default_tps=2.0)
        assert c is not None
        assert c.tokens == 40
        assert c.tps == 2.0

    def test_prompt_overrides_default_tps(self) -> None:
        c = merge_stream_controls(
            "tokens=5 tps=10",
            default_tokens=40,
            default_tps=2.0,
        )
        assert c is not None
        assert c.tokens == 5
        assert c.tps == 10.0

    def test_lorem_cycles(self) -> None:
        text = lorem_token_text(5)
        assert text.split() == ["Lorem", "ipsum", "dolor", "sit", "amet"]


class TestFakeLLMStreamControls(TestCase):
    def test_tokens_tps_slows_sse(self) -> None:
        with FakeLLMServer() as server:
            body = json.dumps({
                "messages": [{"role": "user", "content": "tokens=8 tps=4"}],
            }).encode()
            req = urllib.request.Request(
                f"{server.base_url}/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            t0 = time.monotonic()
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode()
            elapsed = time.monotonic() - t0
            self.assertIn("data:", raw)
            self.assertGreaterEqual(elapsed, 1.0)

    def test_server_default_tokens(self) -> None:
        with FakeLLMServer(default_tokens=6, default_tps=10) as server:
            body = json.dumps({
                "messages": [{"role": "user", "content": "write something"}],
            }).encode()
            req = urllib.request.Request(
                f"{server.base_url}/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            t0 = time.monotonic()
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            self.assertGreaterEqual(time.monotonic() - t0, 0.4)
