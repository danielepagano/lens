"""Pytest fixtures for Lens server tests.

Session-scoped fixtures create one fake LLM server and one test project for
the entire test session, then build a FastAPI TestClient on top of it.
This means the fixtures start up once and are shared across all tests in this
directory — keeping the suite fast while still exercising real project state.

A ``live_server`` fixture is also provided for tests (e.g. Playwright) that
need a real uvicorn process bound to a TCP port rather than the in-process
ASGI TestClient.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project


@pytest.fixture(scope="session")
def fake_llm() -> Generator[FakeLLMServer, None, None]:
    """Start a fake LLM server for the session and stop it afterwards."""
    server = FakeLLMServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def test_project_dir(fake_llm: FakeLLMServer) -> Generator[Path, None, None]:
    """Create a fully-populated Lens project in a temp directory.

    The project has:
    - narrative "story" as the active narrative with an opening passage
    - KB objects: person.amy (protagonist), place.forest
    - person.amy pinned to the root node
    - dataset "testing" enabled
    - mock LLM configured (pointing at the fake_llm fixture)

    The temp directory is cleaned up after the session.
    """
    tmp = tempfile.mkdtemp(prefix="lens_server_test_")
    project_dir = Path(tmp)
    setup_test_project(project_dir, fake_llm.base_url)
    yield project_dir
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def test_client(test_project_dir: Path) -> Generator[TestClient, None, None]:
    """A FastAPI TestClient backed by the session-scoped test project."""
    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    session = ProjectSession(test_project_dir, test_project_dir)
    app = create_app({"test": session})
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def live_server_url(test_project_dir: Path) -> Generator[str, None, None]:
    """Start a real uvicorn process serving the test project and yield its URL.

    Use this fixture when you need a proper HTTP server (e.g. for Playwright
    or httpx async tests) rather than the in-process TestClient.

    The server binds to ``127.0.0.1`` on an OS-assigned port and is shut
    down cleanly after the session.
    """
    import socket

    import uvicorn

    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    session = ProjectSession(test_project_dir, test_project_dir)
    app = create_app({"test": session})

    # Pick a free port.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait until the server is ready.
    import time
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("uvicorn did not start in time")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
