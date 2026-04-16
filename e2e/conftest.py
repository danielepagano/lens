"""Pytest + Playwright fixtures for Lens end-to-end tests.

Setup
-----
Install Playwright support::

    poetry add --group dev pytest-playwright
    playwright install chromium

Run the tests::

    poe test-e2e
    # or directly:
    pytest e2e/ --base-url http://127.0.0.1:8000

Two modes
---------
1. **Auto mode** (default): the conftest spins up a fake LLM and a real
   uvicorn server on a free port, creates a temp project, and tears it all
   down after the session.

2. **External server mode**: set ``LENS_DEV_SERVER_URL`` in your environment
   (e.g. after running ``poe dev``) and the conftest will skip the server
   setup and connect to the already-running server instead.  This is
   useful when testing against a persistent dev project.

   Example::

       LENS_DEV_SERVER_URL=http://127.0.0.1:8000 pytest e2e/

The ``base_url`` for Playwright (and the ``live_server_url`` fixture) always
resolves to the URL of the running API server regardless of mode.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Generator

import pytest

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fake_llm_server() -> Generator[FakeLLMServer | None, None, None]:
    """Start a fake LLM unless we're using an external server."""
    if os.environ.get("LENS_DEV_SERVER_URL"):
        yield None
        return
    server = FakeLLMServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def lens_project_dir(
    fake_llm_server: FakeLLMServer | None,
) -> Generator[Path | None, None, None]:
    """Create a temp Lens project (skipped in external-server mode)."""
    if os.environ.get("LENS_DEV_SERVER_URL"):
        yield None
        return

    assert fake_llm_server is not None
    tmp = tempfile.mkdtemp(prefix="lens_e2e_")
    project_dir = Path(tmp)
    setup_test_project(project_dir, fake_llm_server.base_url)
    yield project_dir
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def live_server_url(
    fake_llm_server: FakeLLMServer | None,
    lens_project_dir: Path | None,
) -> Generator[str, None, None]:
    """URL of the running Lens API server.

    Returns the value of ``LENS_DEV_SERVER_URL`` when set, otherwise starts
    a uvicorn server for the session.
    """
    external = os.environ.get("LENS_DEV_SERVER_URL")
    if external:
        yield external.rstrip("/")
        return

    import uvicorn

    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    assert lens_project_dir is not None
    session = ProjectSession(lens_project_dir, lens_project_dir)
    app = create_app({lens_project_dir.name: session})

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("uvicorn did not start in time")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def project_slug(lens_project_dir: Path | None, live_server_url: str) -> str:
    """Return the project slug for use in API paths.

    In auto mode, uses the temp project directory name.
    In external-server mode, fetches the first slug from GET /projects.
    """
    if lens_project_dir is not None:
        return lens_project_dir.name
    raw = urllib.request.urlopen(f"{live_server_url}/projects").read()
    return str(json.loads(raw)[0]["slug"])


# Make live_server_url available as the Playwright base_url.
@pytest.fixture(scope="session")
def base_url(live_server_url: str) -> str:  # type: ignore[override]
    return live_server_url


