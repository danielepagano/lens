"""API+SSE workflow regression cases (AW-*) from the 1524eaf0→HEAD plan."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from lens.core.knowledge import KnowledgeStore
from lens.core.test.llm_run_mock import mock_run_llm
from lens.testing.regression_fixtures import setup_auto_compress_low_threshold


@pytest.fixture
def compress_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    from lens.testing.fake_llm import FakeLLMServer

    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    fake = FakeLLMServer()
    fake.start()
    try:
        setup_auto_compress_low_threshold(tmp_path, fake.base_url)
    except Exception:
        fake.stop()
        raise

    KnowledgeStore.clear_registry()
    slug = tmp_path.name
    session = ProjectSession(tmp_path, tmp_path)
    app = create_app({slug: session})
    with TestClient(app) as client:
        yield client
    fake.stop()
    KnowledgeStore.clear_registry()


def _collect_stream_with_action(
    client: TestClient,
    url: str,
    body: dict[str, Any],
    *,
    on_plan: Callable[[list[dict[str, Any]], TestClient, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Drain SSE on a worker thread; invoke *on_plan* from the main thread (TestClient-safe)."""
    events: list[dict[str, Any]] = []
    done = threading.Event()
    stream_error: list[BaseException] = []
    slug = url.split("/")[1]
    plan_handled = False

    def _drain() -> None:
        nonlocal plan_handled
        try:
            with client.stream("POST", url, json=body) as response:
                assert response.status_code == 200, response.text
                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    ev = json.loads(line.removeprefix("data: "))
                    events.append(ev)
                    if (
                        on_plan is not None
                        and not plan_handled
                        and ev.get("type") == "workflow"
                        and ev.get("action") == "plan"
                    ):
                        plan_handled = True
                        on_plan(events, client, slug)
        except BaseException as e:  # noqa: BLE001
            stream_error.append(e)
        finally:
            done.set()

    worker = threading.Thread(target=_drain, daemon=True)
    worker.start()
    assert done.wait(timeout=30), "timed out waiting for SSE stream to finish"
    worker.join(timeout=5)
    if stream_error:
        raise stream_error[0]
    return events


class TestWorkflowStreamAw03:
    """AW-03: write stream plan includes auto_compress when fixture threshold met."""

    def test_aw03_plan_includes_auto_compress_step(
        self, compress_client: TestClient, tmp_path: Path
    ) -> None:
        slug = tmp_path.name

        async def _text(*_a: Any, **_k: Any) -> str:
            return "Long generation chunk.\n"

        with patch("lens.core.operator.run_llm", mock_run_llm(_text)):
            with patch(
                "lens.core.auto_compress.run_compress",
                new_callable=AsyncMock,
                return_value=None,
            ):
                events = _collect_stream_with_action(
                    compress_client,
                    f"/{slug}/operator/write",
                    {"prompt": "go", "pins": [], "unpins": []},
                )

        plan = next(
            e
            for e in events
            if e.get("type") == "workflow" and e.get("action") == "plan"
        )
        step_ids = [s["id"] for s in plan.get("steps", [])]
        assert "generate" in step_ids
        assert "auto_compress" in step_ids
        assert "Long generation" in (
            tmp_path / "narrative" / "story" / "_node.md"
        ).read_text(encoding="utf-8")


