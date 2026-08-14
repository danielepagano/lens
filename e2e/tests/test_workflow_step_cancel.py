"""Cancelling a running refine step over the real HTTP stack.

The unit tests drive :class:`WorkflowRunner` directly, so they cannot see the one
thing that actually broke for users: the browser presses a button, and what comes
back over SSE has to be a finished generation, not an aborted one.  This test runs
a real uvicorn server, opens the operator SSE stream, and posts
``{"action": "cancel"}`` while the refine step is mid-flight — exactly what
``StreamingPreviewPanel`` does.
"""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest

from lens.core.generation_artifacts import GenerationArtifacts, GenerationSegment
from lens.core.modalities import (
    Modality,
    ModalityContext,
    RefinePassSpec,
    clear_registry_for_tests,
    ensure_modalities_registered,
    refine_step_id,
    register_modality,
)
from lens.core.pinning import set_modality_config
from lens.core.project import ProjectSession
from lens.core.storage import Storage
from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

PROBE_ID = "refine_probe"
REFINE_STEP = refine_step_id(PROBE_ID)
_STREAM_TIMEOUT_S = 60.0


class _ProbeRefineModality(Modality):
    """Refine pass that tags the text, so an applied pass is visible on disk."""

    id = PROBE_ID

    def workflow_refine_pass(
        self, ctx: ModalityContext, text: str
    ) -> RefinePassSpec | None:
        del ctx
        return RefinePassSpec(
            instruction="polish this",
            apply=lambda _refined: text.rstrip("\n") + "\n<!-- REFINED -->\n",
        )


@pytest.fixture
def refine_server() -> Generator[tuple[str, Path], None, None]:
    """Live server on its own project, with the probe refine modality enabled."""
    import uvicorn

    from lens.server.main import create_app

    clear_registry_for_tests()
    register_modality(_ProbeRefineModality())

    llm = FakeLLMServer()
    llm.start()
    tmp = tempfile.mkdtemp(prefix="lens_refine_cancel_")
    project_dir = Path(tmp)
    session = setup_test_project(project_dir, llm.base_url)

    narrative = session.active_narrative
    assert narrative is not None
    set_modality_config(narrative, PROBE_ID, "enabled", True, Storage(project_dir))
    staging = Storage(project_dir)
    staging.stage_all()
    staging.commit("enable probe modality")

    app = create_app({project_dir.name: ProjectSession(project_dir, project_dir)})
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/health", timeout=1).read()
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    else:  # pragma: no cover - server never came up
        pytest.fail("server did not start")

    try:
        yield f"{base}/{project_dir.name}", project_dir
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        llm.stop()
        clear_registry_for_tests()
        ensure_modalities_registered()


def _post_json(url: str, body: dict[str, Any]) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:  # pragma: no cover - failure detail
        return e.code, e.read().decode()


def _stream_write(
    base: str, events: list[dict[str, Any]], refine_running: threading.Event
) -> None:
    """Read the write SSE stream, flagging when the refine step starts."""
    req = urllib.request.Request(
        f"{base}/operator/write",
        data=json.dumps({"prompt": "go", "pins": [], "unpins": []}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_STREAM_TIMEOUT_S) as r:
        for raw in r:
            line = raw.decode()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            events.append(event)
            if (
                event.get("type") == "workflow"
                and event.get("action") == "step_start"
                and event.get("step_id") == REFINE_STEP
            ):
                refine_running.set()


def test_cancelling_refine_over_http_keeps_the_generation(
    refine_server: tuple[str, Path],
) -> None:
    base, project_dir = refine_server
    events: list[dict[str, Any]] = []
    refine_running = threading.Event()
    refine_saw_cancel = threading.Event()

    async def _blocking_refine(*_a: object, **kwargs: object) -> GenerationArtifacts:
        """Stand in for a slow refine LLM call that honours its cancel event."""
        cancel_event = kwargs.get("cancel_event")
        assert isinstance(cancel_event, asyncio.Event)
        deadline = time.time() + 30
        while time.time() < deadline:
            if cancel_event.is_set():
                refine_saw_cancel.set()
                return GenerationArtifacts(interrupted=True)
            await asyncio.sleep(0.02)
        return GenerationArtifacts(
            segments=[GenerationSegment("prose", "refined\n")]
        )

    with patch(
        "lens.core.modalities.workflow.run_refine_pass",
        side_effect=_blocking_refine,
    ):
        reader = threading.Thread(
            target=_stream_write, args=(base, events, refine_running), daemon=True
        )
        reader.start()

        assert refine_running.wait(timeout=_STREAM_TIMEOUT_S), "refine step never started"
        status, body = _post_json(
            f"{base}/stream/workflow/action",
            {"step_id": REFINE_STEP, "action": "cancel"},
        )
        assert status == 200, body

        reader.join(timeout=_STREAM_TIMEOUT_S)
        assert not reader.is_alive(), "stream never finished"

    assert refine_saw_cancel.is_set(), "refine LLM call was not interrupted"

    plan = next(
        e
        for e in events
        if e.get("type") == "workflow"
        and e.get("action") == "plan"
        and any(s["id"] == REFINE_STEP for s in e.get("steps", []))
    )
    refine_plan = next(s for s in plan["steps"] if s["id"] == REFINE_STEP)
    assert refine_plan.get("cancel_scope") == "step", (
        "the browser cannot tell a step-scoped cancel apart without this flag"
    )

    done = next(e for e in events if e.get("type") == "done")
    assert done.get("interrupted") is False
    statuses = {s["id"]: s["status"] for s in done.get("steps", [])}
    assert statuses[REFINE_STEP] == "skipped"
    assert statuses["persist"] == "success"

    node = ProjectSession(project_dir, project_dir).active_narrative
    assert node is not None
    text = node.md_path().read_text(encoding="utf-8")
    assert "<!-- REFINED -->" not in text, "cancelled pass must not apply"
    assert "[write" in text, "the generation must still be persisted"
