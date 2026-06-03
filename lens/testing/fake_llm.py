"""Minimal fake OpenAI-compatible streaming LLM server for tests.

Usage::

    server = FakeLLMServer()
    server.start()
    # use server.base_url as the LLM base_url in lens.toml
    server.stop()

Or as a context manager::

    with FakeLLMServer() as server:
        print(server.base_url)

Stream speed
------------
Anywhere in the request messages, include::

    tokens=120 tps=4

``tokens`` — how many words to emit (cycles through Lorem ipsum).
``tps`` — tokens per second (delay ``1/tps`` between chunks).  Omit ``tps`` to
use the server's ``stream_chunk_delay`` (legacy per-word delay) or bench default.

The e2e sandbox and bench mock server can also set default ``tokens`` / ``tps``
when the prompt omits them (``poe e2e-sandbox --tokens 80 --tps 2``).

Special triggers
----------------
``FAKE_SECRET_TRIGGER``
    Response includes an ``ai:secret:`` block (see module constants).

``TEXT TO SUMMARIZE:`` (session summary template)
    Integration-summary style header plus streamed body.

``You may call kb_patch only for these targets`` (remember template)
    Empty by default; with ``tokens=…`` streams visible placeholder text so you
    can exercise cancel/skip on the remember step in the UI.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from lens.testing.stream_controls import (
    StreamControls,
    lorem_token_text,
    merge_stream_controls,
)

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris."
)

# Must match the task footer used in ``session.summary_instruction_template`` and
# ``play.summary_instruction_template`` in ``lens/prompts/default.toml``.
_SUMMARY_REQUEST_MARKER = "TEXT TO SUMMARIZE:"

# Distinctive line from ``remember.instruction_template`` in ``lens/prompts/default.toml``.
_REMEMBER_TASK_MARKER = "You may call kb_patch only for these targets"

# Secret-encoding test support.
FAKE_SECRET_TRIGGER = "EMIT_FAKE_SECRET"
FAKE_SECRET_PLAINTEXT = "the king betrayed everyone"
FAKE_SECRET_ROT13 = "gur xvat orgenlrq rirelbar"

MOCK_LLM_DEFAULT_PORT = 18765


def _sse_chunk(content: str) -> bytes:
    payload = json.dumps({
        "choices": [{"delta": {"content": content}, "finish_reason": None}]
    })
    return f"data: {payload}\n\n".encode()


def _stream_words(
    wfile: Any,
    words: list[str],
    *,
    delay: float,
    prefix: str = "",
    suffix: str = "",
) -> None:
    if prefix:
        wfile.write(_sse_chunk(prefix))
        wfile.flush()
    for i, word in enumerate(words):
        piece = word if i == 0 and not prefix else f" {word}"
        wfile.write(_sse_chunk(piece))
        wfile.flush()
        if delay > 0 and i + 1 < len(words):
            time.sleep(delay)
    if suffix:
        wfile.write(_sse_chunk(suffix))
        wfile.flush()
    wfile.write(b"data: [DONE]\n\n")
    wfile.flush()


def _words_for_controls(controls: StreamControls, *, tail: str = "") -> list[str]:
    body = lorem_token_text(controls.tokens, suffix=tail)
    if body:
        return list(body.split())
    return list(tail.split()) if tail else []


def _server_defaults(handler: BaseHTTPRequestHandler) -> tuple[float, int | None, float | None]:
    srv = handler.server
    chunk_delay = float(getattr(srv, "stream_chunk_delay", 0.0))
    default_tokens = getattr(srv, "default_tokens", None)
    default_tps = getattr(srv, "default_tps", None)
    return chunk_delay, default_tokens, default_tps


def _plan_stream(
    msg_text: str,
    total_chars: int,
    *,
    chunk_delay: float,
    default_tokens: int | None,
    default_tps: float | None,
) -> tuple[str, list[str], float, bool, str]:
    """Return ``(prefix, words, delay, empty_immediate, trailing_chunk)``."""
    controls = merge_stream_controls(
        msg_text,
        default_tokens=default_tokens,
        default_tps=default_tps,
    )
    delay = (
        controls.delay_seconds(fallback_delay=chunk_delay)
        if controls
        else chunk_delay
    )

    if _REMEMBER_TASK_MARKER in msg_text:
        if controls is None:
            return "", [], 0.0, True, ""
        return "", _words_for_controls(controls), delay, False, ""

    if FAKE_SECRET_TRIGGER in msg_text:
        secret_tail = f"\n\n<!-- ai:secret:\n{FAKE_SECRET_PLAINTEXT}\n-->"
        if controls:
            return "", _words_for_controls(controls), delay, False, secret_tail
        return "", list((LOREM + secret_tail).split()), chunk_delay, False, ""

    if _SUMMARY_REQUEST_MARKER in msg_text:
        prefix = "Integration Summary\n\n"
        tail = f" [input:{total_chars}]"
        if controls:
            return prefix, _words_for_controls(controls, tail=tail), delay, False, ""
        return prefix, list((LOREM + tail).split()), chunk_delay, False, ""

    tail = f" [input:{total_chars}]"
    if controls:
        return "", _words_for_controls(controls, tail=tail), delay, False, ""
    return "", list((LOREM + tail).split()), chunk_delay, False, ""


class _FakeLLMHandler(BaseHTTPRequestHandler):
    """Serve one fake SSE streaming completion per POST to /v1/chat/completions."""

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data: dict[str, Any] = json.loads(body) if body else {}
            messages: list[dict[str, Any]] = data.get("messages", [])
            total_chars = sum(len(m.get("content", "")) for m in messages)
            msg_text = " ".join(m.get("content", "") for m in messages)

            chunk_delay, default_tokens, default_tps = _server_defaults(self)
            prefix, words, delay, empty, trailing = _plan_stream(
                msg_text,
                total_chars,
                chunk_delay=chunk_delay,
                default_tokens=default_tokens,
                default_tps=default_tps,
            )

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            if empty:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                return

            _stream_words(
                self.wfile,
                words,
                delay=delay,
                prefix=prefix,
                suffix=trailing,
            )
        except Exception:  # noqa: BLE001
            pass

    def log_message(self, format: str, *args: Any) -> None:  # silence server logs
        pass


class FakeLLMServer:
    """OpenAI-compatible SSE streaming server for integration tests and bench mock."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        stream_chunk_delay: float = 0.0,
        default_tokens: int | None = None,
        default_tps: float | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self.stream_chunk_delay = stream_chunk_delay
        self.default_tokens = default_tokens
        self.default_tps = default_tps
        self._server = HTTPServer((host, port), _FakeLLMHandler)
        self._server.stream_chunk_delay = stream_chunk_delay  # type: ignore[attr-defined]
        self._server.default_tokens = default_tokens  # type: ignore[attr-defined]
        self._server.default_tps = default_tps  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )

    @property
    def base_url(self) -> str:
        addr = self._server.server_address
        return f"http://{addr[0]}:{addr[1]}"

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def set_stream_defaults(
        self,
        tokens: int | None,
        tps: float | None,
    ) -> None:
        """Update default ``tokens``/``tps`` for requests that omit prompt directives."""
        self.default_tokens = tokens
        self.default_tps = tps
        self._server.default_tokens = tokens  # type: ignore[attr-defined]
        self._server.default_tps = tps  # type: ignore[attr-defined]

    @contextmanager
    def fast_setup(self) -> Generator[None]:
        """Disable stream defaults while seeding a project (restore on exit)."""
        saved = (self.default_tokens, self.default_tps)
        self.set_stream_defaults(None, None)
        try:
            yield
        finally:
            self.set_stream_defaults(saved[0], saved[1])

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FakeLLMServer:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
