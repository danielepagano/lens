"""Minimal fake A2E text-to-image server for tests.

Mirrors the verified live shapes:

*  ``POST /api/v1/userText2Image/start`` — returns
   ``{code:0, data:[<task>...], trace_id}`` with one entry per
   ``max_images``.  Each task starts in ``current_status: "initialized"``.
*  ``GET /api/v1/userText2Image/{_id}`` — task-detail; the configured number
   of polls return ``"processing"``, then ``"completed"`` with an
   ``image_urls`` URL pointing back at this same fake server.
*  ``POST /api/v1/userText2Image/batchDetail`` — returns
   ``{code:0, data:[<task>...]}`` with the same per-task shape.
*  ``GET /fake-image/<id>.png`` — serves a tiny valid PNG.

Usage::

    with FakeImageServer() as server:
        # use server.base_url as [[image]] base_url in lens.toml
        ...

Configuration:

*  ``processing_polls`` — number of poll responses returned as
   ``"processing"`` before a task flips to ``"completed"`` (default 1).
*  ``fail_ids`` — task ids that should flip to ``"failed"`` instead of
   ``"completed"`` so the failure path is testable.

The server records every ``/start`` request body in
:attr:`FakeImageServer.start_requests` so tests can assert exactly what was
sent (resolved prompt, translated dimensions, etc.).
"""

from __future__ import annotations

import json
import threading
import uuid
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast
from urllib.parse import urlparse

# Smallest valid PNG: 1x1 fully-white image (67 bytes, hand-crafted).
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63f8ffff3f0005fe02fe65b48d680000000049454e44ae426082"
)


class FakeImageServer:
    """In-process A2E mock with deterministic poll behavior."""

    def __init__(
        self,
        *,
        processing_polls: int = 1,
        fail_ids: set[str] | None = None,
    ) -> None:
        self._processing_polls = max(0, processing_polls)
        self._fail_ids: set[str] = fail_ids or set()
        self.start_requests: list[dict[str, Any]] = []
        self._tasks: dict[str, dict[str, Any]] = {}
        self._poll_counts: dict[str, int] = defaultdict(int)
        handler = self._make_handler()
        self._server = HTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[0], self._server.server_address[1]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FakeImageServer:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Task lifecycle (driven by the handler)
    # ------------------------------------------------------------------

    def _create_tasks(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        n = max(1, int(body.get("max_images", 1)))
        prompt = str(body.get("prompt", ""))
        tasks: list[dict[str, Any]] = []
        for _ in range(n):
            tid = uuid.uuid4().hex[:24]
            task: dict[str, Any] = {
                "_id": tid,
                "featureType": "text2image",
                "name": str(body.get("name", "")) or tid,
                "prompt": prompt,
                "image_urls": [],
                "input_images": [],
                "current_status": "initialized",
                "failed_message": "",
                "failed_code": "",
                "width": int(body.get("width", 1024)),
                "height": int(body.get("height", 1024)),
                "model_type": str(body.get("model_type", "a2e")),
                "model_version": "test",
                "aspect_ratio": body.get("aspect_ratio"),
            }
            self._tasks[tid] = task
            tasks.append(dict(task))
        return tasks

    def _advance(self, tid: str) -> dict[str, Any]:
        """Advance the task state machine and return the current snapshot."""
        task = self._tasks[tid]
        if task["current_status"] in {"completed", "failed"}:
            return dict(task)
        self._poll_counts[tid] += 1
        if self._poll_counts[tid] <= self._processing_polls:
            task["current_status"] = "processing"
            return dict(task)
        # Past the processing window — flip to a terminal status.
        if tid in self._fail_ids:
            task["current_status"] = "failed"
            task["failed_message"] = "fake failure for tests"
            task["failed_code"] = "FAKE_FAIL"
        else:
            task["current_status"] = "completed"
            task["image_urls"] = [f"{self.base_url}/fake-image/{tid}.png"]
        return dict(task)

    # ------------------------------------------------------------------
    # HTTP handler
    # ------------------------------------------------------------------

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # silence
                pass

            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    return {}
                if not isinstance(parsed, dict):
                    return {}
                return cast(dict[str, Any], parsed)

            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path == "/api/v1/userText2Image/start":
                    body = self._read_json()
                    server.start_requests.append(body)
                    tasks = server._create_tasks(body)
                    self._send_json(
                        200,
                        {"code": 0, "data": tasks, "trace_id": uuid.uuid4().hex},
                    )
                    return
                if path == "/api/v1/userText2Image/batchDetail":
                    body = self._read_json()
                    ids_raw = body.get("ids", [])
                    ids: list[str] = []
                    if isinstance(ids_raw, list):
                        for item in cast(list[Any], ids_raw):
                            if isinstance(item, str):
                                ids.append(item)
                    data = [server._advance(tid) for tid in ids if tid in server._tasks]
                    self._send_json(200, {"code": 0, "data": data})
                    return
                self._send_json(404, {"code": -1, "message": "not found"})

            def do_GET(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if path.startswith("/fake-image/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(_TINY_PNG)))
                    self.end_headers()
                    self.wfile.write(_TINY_PNG)
                    return
                if path.startswith("/api/v1/userText2Image/"):
                    tid = path.rsplit("/", 1)[-1]
                    if tid not in server._tasks:
                        self._send_json(404, {"code": -1, "message": "not found"})
                        return
                    snapshot = server._advance(tid)
                    self._send_json(200, {"code": 0, "data": snapshot})
                    return
                self._send_json(404, {"code": -1, "message": "not found"})

        return _Handler
