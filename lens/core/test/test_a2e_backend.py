"""Tests for the A2E image backend.

Hits a local :class:`FakeImageServer` rather than the real A2E API.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from lens.core.image.api import a2e as a2e_mod
from lens.core.image.api.a2e import A2EBackend, resolve_dimensions
from lens.core.image.backend import ImageError
from lens.core.image.spec import (
    Done,
    Error,
    ImageEvent,
    ImageSpec,
    ItemReady,
)
from lens.testing.fake_image import FakeImageServer


def _spec(batch: int = 1, aspect: str = "1:1", size: str = "1k") -> ImageSpec:
    return ImageSpec(
        prompt="a tiny red cube",
        aspect_ratio=aspect,
        size=size,
        batch=batch,
        model_id="a2e",
    )


def _run(backend: A2EBackend, spec: ImageSpec) -> list[ImageEvent]:
    async def collect() -> list[ImageEvent]:
        events: list[ImageEvent] = []
        async for event in backend.generate(spec):
            events.append(event)
        return events

    return asyncio.run(collect())


class DimensionResolutionTests(unittest.TestCase):
    def test_1k_square(self) -> None:
        self.assertEqual(resolve_dimensions("1:1", "1k"), (1024, 1024))

    def test_1k_portrait(self) -> None:
        self.assertEqual(resolve_dimensions("9:16", "1k"), (768, 1344))

    def test_2k_landscape(self) -> None:
        self.assertEqual(resolve_dimensions("16:9", "2k"), (2688, 1536))

    def test_unsupported_size_raises(self) -> None:
        with self.assertRaises(ImageError):
            resolve_dimensions("1:1", "4k")

    def test_unsupported_aspect_raises(self) -> None:
        with self.assertRaises(ImageError):
            resolve_dimensions("99:1", "1k")


class A2EBackendTests(unittest.TestCase):
    def test_single_image_completes(self) -> None:
        with FakeImageServer(processing_polls=0) as server:
            backend = A2EBackend(
                api_key="sk_test",
                base_url=server.base_url,
                model_type="a2e",
                timeout_seconds=30.0,
            )
            # Speed up the polling loop for tests.
            with _fast_polling():
                events = _run(backend, _spec(batch=1))
            items = [e for e in events if isinstance(e, ItemReady)]
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertGreater(len(item.data), 0)
            self.assertEqual(item.ext, "png")
            self.assertIn("task_id", item.metadata)
            self.assertEqual(item.metadata["width"], 1024)
            self.assertEqual(item.metadata["height"], 1024)
            self.assertEqual(item.metadata["model_type"], "a2e")
            # Done should be the last event.
            self.assertIsInstance(events[-1], Done)
            # /start was called once with the right body.
            self.assertEqual(len(server.start_requests), 1)
            req = server.start_requests[0]
            self.assertEqual(req["prompt"], "a tiny red cube")
            self.assertEqual(req["max_images"], 1)
            self.assertEqual(req["model_type"], "a2e")
            self.assertEqual(req["width"], 1024)
            self.assertEqual(req["height"], 1024)

    def test_batch_of_three_returns_three_items(self) -> None:
        with FakeImageServer(processing_polls=1) as server:
            backend = A2EBackend(
                api_key="sk_test",
                base_url=server.base_url,
                model_type="a2e",
                timeout_seconds=30.0,
            )
            with _fast_polling():
                events = _run(backend, _spec(batch=3, aspect="16:9"))
            items = [e for e in events if isinstance(e, ItemReady)]
            self.assertEqual(len(items), 3)
            # Indices 0..2 in submission order.
            self.assertEqual([i.index for i in items], [0, 1, 2])
            self.assertEqual(server.start_requests[0]["max_images"], 3)
            self.assertEqual(server.start_requests[0]["width"], 1344)
            self.assertEqual(server.start_requests[0]["height"], 768)

    def test_failed_task_emits_error(self) -> None:
        with FakeImageServer(processing_polls=0) as server:
            backend = A2EBackend(
                api_key="sk_test",
                base_url=server.base_url,
                model_type="a2e",
                timeout_seconds=30.0,
            )
            # Hook the server to mark the next task as failed at create time.
            original = server._create_tasks  # type: ignore[attr-defined]

            def _fail_all(body: dict[str, Any]) -> list[dict[str, Any]]:
                tasks = original(body)  # type: ignore[no-any-return]
                for t in tasks:
                    server._fail_ids.add(t["_id"])  # type: ignore[attr-defined]
                return tasks

            server._create_tasks = _fail_all  # type: ignore[attr-defined]

            with _fast_polling():
                events = _run(backend, _spec(batch=1))
            errors = [e for e in events if isinstance(e, Error)]
            self.assertTrue(errors, f"expected an Error event, got {events}")
            self.assertIn("failed", errors[0].message.lower())

    def test_seedream_uses_aspect_ratio_not_dimensions(self) -> None:
        with FakeImageServer(processing_polls=0) as server:
            backend = A2EBackend(
                api_key="sk_test",
                base_url=server.base_url,
                model_type="seedream",
                timeout_seconds=30.0,
            )
            with _fast_polling():
                _run(backend, _spec(aspect="3:2"))
            req = server.start_requests[0]
            self.assertEqual(req["model_type"], "seedream")
            self.assertEqual(req["aspect_ratio"], "3:2")
            self.assertNotIn("width", req)
            self.assertNotIn("height", req)

    def test_input_images_passed_to_start(self) -> None:
        with FakeImageServer(processing_polls=0) as server:
            backend = A2EBackend(
                api_key="sk_test",
                base_url=server.base_url,
                model_type="a2e",
                timeout_seconds=30.0,
            )
            spec = ImageSpec(
                prompt="with refs",
                aspect_ratio="1:1",
                size="1k",
                batch=1,
                model_id="a2e",
                input_image_urls=(
                    "https://example.com/a.jpg",
                    "https://example.com/b.jpg",
                ),
            )
            with _fast_polling():
                _run(backend, spec)
            req = server.start_requests[0]
            self.assertEqual(
                req["input_images"],
                ["https://example.com/a.jpg", "https://example.com/b.jpg"],
            )


class _fast_polling:
    """Patch a2e poll constants so tests don't sleep for seconds."""

    def __enter__(self) -> None:
        self._orig_initial = a2e_mod.INITIAL_POLL_DELAY
        self._orig_max = a2e_mod.MAX_POLL_DELAY
        a2e_mod.INITIAL_POLL_DELAY = 0.01
        a2e_mod.MAX_POLL_DELAY = 0.02

    def __exit__(self, *_: object) -> None:
        a2e_mod.INITIAL_POLL_DELAY = self._orig_initial
        a2e_mod.MAX_POLL_DELAY = self._orig_max


if __name__ == "__main__":
    unittest.main()
