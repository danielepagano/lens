"""Playwright browser tests for the Lens UI.

These tests run against the same in-process uvicorn server used by the other
e2e tests (see ``e2e/conftest.py``).  They require Playwright *and* a
Chromium browser installation::

    playwright install chromium

Then run with::

    poe test-e2e
    # or directly:
    pytest e2e/tests/test_browser.py -v

The module is automatically skipped when Chromium is not available, so it
is safe to include in the normal ``poe test-e2e`` run on headless CI as long
as the browser is installed there.

UI not yet implemented
----------------------
The tests below are stubs — they confirm the server responds to HTTP requests
that a browser would make (health + static root), providing a starting point
once the frontend exists.  Replace or expand them as the UI is built.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _chromium_available() -> bool:
    """Ask playwright for its Chromium executable path and verify it exists.

    Runs in a subprocess so that importing playwright.sync_api (which triggers
    websockets deprecation warnings) doesn't pollute the test session output.
    Returns False on any error (playwright not installed, browser missing, etc.)
    """
    probe = (
        "from playwright.sync_api import sync_playwright;"
        "p=sync_playwright().__enter__();"
        "import sys, pathlib;"
        "sys.exit(0 if pathlib.Path(p.chromium.executable_path).exists() else 1)"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-W", "ignore", "-c", probe],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _chromium_available(),
    reason="Playwright Chromium not installed — run: playwright install chromium",
)


class TestBrowser:
    """Smoke tests exercising the running Lens server via a real browser."""

    def test_health_via_browser(self, page: "Page", live_server_url: str) -> None:  # type: ignore[name-defined]  # noqa: F821
        """The /health endpoint is reachable and returns a 200 page."""
        response = page.goto(f"{live_server_url}/health")
        assert response is not None
        assert response.status == 200

    def test_root_responds(self, page: "Page", live_server_url: str) -> None:  # type: ignore[name-defined]  # noqa: F821
        """The server root responds (200 or 404 — either way it's up)."""
        response = page.goto(live_server_url)
        assert response is not None
        assert response.status in (200, 404)
