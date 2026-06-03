"""A2E text-to-image backend (https://video.a2e.ai).

Job-based: ``POST /start`` kicks off generation; we then poll
``POST /batchDetail`` (or ``GET /{_id}``) until each task hits a terminal
status, then fetch the resulting image bytes from the public CDN URL.

Response shapes were verified empirically against the live API on 2026-04-27.
See ``docs/lens-visuals-design.md`` for the recorded payload examples.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx

from lens.core.image.backend import ImageBackend, ImageError
from lens.core.image.spec import (
    Done,
    Error,
    ImageApiCapabilities,
    ImageEvent,
    ImageSpec,
    ItemReady,
    Progress,
)

logger = logging.getLogger(__name__)

API_CAPABILITIES = ImageApiCapabilities(supports_reference_images=True)


# Aspect ratio + size category → (width, height) in pixels.  Used only for the
# native ``a2e`` model (``seedream`` accepts ``aspect_ratio`` directly).
_DIMENSION_TABLE: dict[str, dict[str, tuple[int, int]]] = {
    "1k": {
        "1:1": (1024, 1024),
        "16:9": (1344, 768),
        "9:16": (768, 1344),
        "4:3": (1152, 896),
        "3:4": (896, 1152),
        "3:2": (1216, 832),
        "2:3": (832, 1216),
        "21:9": (1536, 640),
    },
    "2k": {
        "1:1": (2048, 2048),
        "16:9": (2688, 1536),
        "9:16": (1536, 2688),
        "4:3": (2304, 1792),
        "3:4": (1792, 2304),
        "3:2": (2432, 1664),
        "2:3": (1664, 2432),
        "21:9": (3072, 1280),
    },
}

_TERMINAL_STATUSES = frozenset({"completed", "failed"})

# Initial and max poll intervals (seconds).  Module-level so tests can patch
# them down for fast turnaround; production callers shouldn't override.
INITIAL_POLL_DELAY = 3.0
MAX_POLL_DELAY = 10.0


def _ext_from_url(url: str) -> str:
    """Extract a lowercase file extension (without dot) from a URL path."""
    path = url.split("?", 1)[0].split("#", 1)[0]
    name = os.path.basename(path)
    if "." in name:
        return name.rsplit(".", 1)[-1].lower()
    return "jpg"


def _ext_from_content_type(ctype: str) -> str | None:
    ctype = ctype.lower().split(";", 1)[0].strip()
    mapping = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    return mapping.get(ctype)


def resolve_dimensions(aspect: str, size: str) -> tuple[int, int]:
    """Translate an ``aspect_ratio + size`` pair to ``(width, height)`` pixels.

    Public so unit tests can verify the table without reaching into privates.
    """
    if size not in _DIMENSION_TABLE:
        raise ImageError(
            f"A2E backend: unsupported size {size!r} (supported: "
            f"{sorted(_DIMENSION_TABLE.keys())})"
        )
    table = _DIMENSION_TABLE[size]
    if aspect not in table:
        raise ImageError(
            f"A2E backend: unsupported aspect {aspect!r} for size {size!r} "
            f"(supported: {sorted(table.keys())})"
        )
    return table[aspect]


class A2EBackend(ImageBackend):
    """Image backend for A2E's ``userText2Image`` API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_type: str,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_type = model_type
        self._timeout_seconds = timeout_seconds

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, spec: ImageSpec) -> AsyncIterator[ImageEvent]:
        return self._stream(spec)

    async def _stream(self, spec: ImageSpec) -> AsyncIterator[ImageEvent]:
        if spec.batch < 1 or spec.batch > 8:
            yield Error(f"A2E supports batch size 1-8 (requested {spec.batch})")
            return

        body = self._build_request_body(spec)
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            yield Progress(phase="submit", message=f"submitting batch={spec.batch}")
            try:
                resp = await client.post(
                    f"{self._base_url}/api/v1/userText2Image/start",
                    headers=self._headers,
                    json=body,
                )
            except httpx.HTTPError as e:
                yield Error(f"A2E /start failed: {e}")
                return

            if resp.status_code != 200:
                yield Error(
                    f"A2E /start returned HTTP {resp.status_code}: {resp.text[:300]}"
                )
                return

            payload = self._parse_json(resp)
            if payload is None:
                yield Error("A2E /start returned non-JSON response")
                return

            if int(payload.get("code", -1)) != 0:
                yield Error(
                    f"A2E /start error: {payload.get('message') or payload}"
                )
                return

            tasks_raw: Any = payload.get("data") or []
            if not isinstance(tasks_raw, list) or not tasks_raw:
                yield Error("A2E /start returned no tasks in 'data'")
                return
            task_ids: list[str] = []
            for entry in cast(list[Any], tasks_raw):
                if isinstance(entry, dict):
                    entry_d = cast(dict[str, Any], entry)
                    tid = entry_d.get("_id")
                    if isinstance(tid, str) and tid:
                        task_ids.append(tid)
            if not task_ids:
                yield Error("A2E /start: no task ids in response 'data[*]._id'")
                return

            yield Progress(
                phase="submitted",
                message=f"task_ids={task_ids}",
            )

            # Poll until all tasks hit a terminal status (or timeout).
            results: dict[str, dict[str, Any]] = {}
            elapsed = 0.0
            delay = INITIAL_POLL_DELAY
            while True:
                pending = [tid for tid in task_ids if tid not in results]
                if not pending:
                    break
                if elapsed >= self._timeout_seconds:
                    yield Error(
                        f"A2E timeout after {self._timeout_seconds:.0f}s "
                        f"({len(results)}/{len(task_ids)} done)"
                    )
                    return

                await asyncio.sleep(delay)
                elapsed += delay
                delay = min(MAX_POLL_DELAY, delay * 1.3)

                try:
                    poll = await client.post(
                        f"{self._base_url}/api/v1/userText2Image/batchDetail",
                        headers=self._headers,
                        json={"ids": pending},
                    )
                except httpx.HTTPError as e:
                    yield Progress(phase="poll", message=f"transient error: {e}")
                    continue

                if poll.status_code != 200:
                    yield Progress(
                        phase="poll",
                        message=f"HTTP {poll.status_code} (will retry)",
                    )
                    continue

                poll_payload = self._parse_json(poll)
                if poll_payload is None or int(poll_payload.get("code", -1)) != 0:
                    yield Progress(phase="poll", message="non-zero code (will retry)")
                    continue

                tasks: Any = poll_payload.get("data") or []
                if not isinstance(tasks, list):
                    yield Progress(phase="poll", message="bad payload shape")
                    continue
                for task_any in cast(list[Any], tasks):
                    if not isinstance(task_any, dict):
                        continue
                    task = cast(dict[str, Any], task_any)
                    tid_any = task.get("_id")
                    if not isinstance(tid_any, str):
                        continue
                    status = task.get("current_status", "")
                    if status in _TERMINAL_STATUSES:
                        results[tid_any] = task

                yield Progress(
                    phase="poll",
                    message=f"{len(results)}/{len(task_ids)} done",
                )

            # Download bytes for each completed task in submission order.
            for index, tid in enumerate(task_ids):
                task = results[tid]
                status = task.get("current_status")
                if status == "failed":
                    msg = task.get("failed_message") or "unknown failure"
                    yield Error(f"A2E task {tid} failed: {msg}")
                    return
                urls_raw: Any = task.get("image_urls") or []
                if not isinstance(urls_raw, list) or not urls_raw:
                    yield Error(f"A2E task {tid} completed without image_urls")
                    return
                first_url = next(
                    (u for u in cast(list[Any], urls_raw) if isinstance(u, str)),
                    None,
                )
                if first_url is None:
                    yield Error(f"A2E task {tid} image_urls had no string entries")
                    return

                try:
                    img_resp = await client.get(first_url)
                except httpx.HTTPError as e:
                    yield Error(f"A2E image fetch failed for {tid}: {e}")
                    return
                if img_resp.status_code != 200:
                    yield Error(
                        f"A2E image fetch HTTP {img_resp.status_code} for {tid}"
                    )
                    return
                ext = (
                    _ext_from_content_type(img_resp.headers.get("content-type", ""))
                    or _ext_from_url(first_url)
                )
                metadata: dict[str, Any] = {
                    "task_id": tid,
                    "result_url": first_url,
                    "prompt_sent": spec.prompt,
                    "prompt_used": task.get("prompt"),
                    "width": task.get("width"),
                    "height": task.get("height"),
                    "model_type": task.get("model_type"),
                    "model_version": task.get("model_version"),
                }
                yield ItemReady(
                    index=index,
                    data=img_resp.content,
                    ext=ext,
                    metadata=metadata,
                )

            yield Done()

    def _build_request_body(self, spec: ImageSpec) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": spec.prompt,
            "model_type": self._model_type,
            "max_images": spec.batch,
        }
        if self._model_type == "seedream":
            body["aspect_ratio"] = spec.aspect_ratio
        else:
            width, height = resolve_dimensions(spec.aspect_ratio, spec.size)
            body["width"] = width
            body["height"] = height
        if spec.input_image_urls:
            body["input_images"] = list(spec.input_image_urls)
        return body

    @staticmethod
    def _parse_json(resp: httpx.Response) -> dict[str, Any] | None:
        try:
            data = resp.json()
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        return cast(dict[str, Any], data)
