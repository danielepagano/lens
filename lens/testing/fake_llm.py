"""Minimal fake OpenAI-compatible streaming LLM server for tests.

Usage::

    server = FakeLLMServer()
    server.start()
    # use server.base_url as the LLM base_url in lens.toml
    server.stop()

Or as a context manager::

    with FakeLLMServer() as server:
        print(server.base_url)

Special triggers
----------------
The fake LLM recognises one magic trigger in the request messages:

``FAKE_SECRET_TRIGGER``
    If this string appears anywhere in the concatenated message content, the
    response includes an ``ai:secret:`` block with ``FAKE_SECRET_PLAINTEXT``.
    The storage layer ROT13-encodes that block on write; tests can assert the
    stored file contains ``FAKE_SECRET_ROT13`` and not the plaintext.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris."
)

# Secret-encoding test support.
FAKE_SECRET_TRIGGER = "EMIT_FAKE_SECRET"
FAKE_SECRET_PLAINTEXT = "the king betrayed everyone"
FAKE_SECRET_ROT13 = "gur xvat orgenlrq rirelbar"


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

            if FAKE_SECRET_TRIGGER in msg_text:
                response_text = (
                    f"{LOREM}\n\n<!-- ai:secret:\n{FAKE_SECRET_PLAINTEXT}\n-->"
                )
            else:
                response_text = f"{LOREM} [input:{total_chars}]"

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            for word in response_text.split():
                chunk = json.dumps({
                    "choices": [{"delta": {"content": word + " "}, "finish_reason": None}]
                })
                self.wfile.write(f"data: {chunk}\n\n".encode())
                self.wfile.flush()

            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except Exception:  # noqa: BLE001
            pass

    def log_message(self, format: str, *args: Any) -> None:  # silence server logs
        pass


class FakeLLMServer:
    """A minimal OpenAI-compatible SSE streaming server for integration tests.

    Responds to any POST request with a Lorem Ipsum stream followed by
    ``[input:<N>]`` where N is the total character count of the messages sent.
    This lets tests verify that context is being assembled and sent correctly.

    If ``FAKE_SECRET_TRIGGER`` appears in the messages, responds with a Lorem
    Ipsum stream that includes an ``ai:secret:`` block (see module docstring).
    """

    def __init__(self) -> None:
        self._server = HTTPServer(("127.0.0.1", 0), _FakeLLMHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        addr = self._server.server_address
        return f"http://{addr[0]}:{addr[1]}"

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
