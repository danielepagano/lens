"""Playwright browser tests for the Lens UI.

These tests run against the same in-process uvicorn server used by the other
e2e tests (see ``e2e/conftest.py``).  They require Playwright *and* a
Chromium browser installation::

    playwright install chromium

Then run with::

    poe test-e2e
    # or directly:
    pytest e2e/tests/test_browser.py -v

The module is automatically skipped when Chromium is not available or the
frontend has not been built, so it is safe to include in the normal
``poe test-e2e`` run.  ``poe check`` runs ``build-ui`` before ``test-e2e``
so the static assets will be present.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page


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


_STATIC_BUILT = (
    pathlib.Path(__file__).parent.parent.parent / "lens/server/static/index.html"
)

pytestmark = pytest.mark.skipif(
    not _chromium_available() or not _STATIC_BUILT.exists(),
    reason="Run 'poe build-ui' and 'playwright install chromium' first",
)


class TestBrowser:
    """UI tests exercising the Lens frontend via a real browser."""

    def test_page_loads(self, page: "Page", live_server_url: str) -> None:
        """The root page loads and renders the top bar and tree browser."""
        page.goto(live_server_url)  # type: ignore[union-attr]
        page.wait_for_selector('[data-testid="top-bar"]')  # type: ignore[union-attr]
        page.wait_for_selector('[data-testid="tree-browser"]')  # type: ignore[union-attr]
        assert page.is_visible('[data-testid="top-bar"]')  # type: ignore[union-attr]
        assert page.is_visible('[data-testid="tree-browser"]')  # type: ignore[union-attr]

    def test_tree_has_nodes(self, page: "Page", live_server_url: str) -> None:
        """The tree browser renders at least one node button."""
        page.goto(live_server_url)  # type: ignore[union-attr]
        page.wait_for_selector('[data-testid="tree-browser"] button[data-address]')  # type: ignore[union-attr]
        buttons = page.query_selector_all('[data-testid="tree-browser"] button[data-address]')  # type: ignore[union-attr]
        assert len(buttons) >= 1  # type: ignore[arg-type]

    def test_node_navigation(self, page: "Page", live_server_url: str) -> None:
        """Clicking the 'story' node loads Lorem ipsum content in MarkdownView."""
        page.goto(live_server_url)  # type: ignore[union-attr]
        page.wait_for_selector('[data-testid="tree-browser"] button[data-address]')  # type: ignore[union-attr]
        story_btn = page.query_selector('[data-testid="tree-browser"] button[data-address="story"]')  # type: ignore[union-attr]
        assert story_btn is not None, "Expected a 'story' node button in the tree"
        story_btn.click()
        page.wait_for_selector('[data-testid="markdown-view"]')  # type: ignore[union-attr]
        content: str = page.inner_text('[data-testid="markdown-view"]')  # type: ignore[union-attr]
        assert "Lorem" in content, f"Expected Lorem ipsum in markdown view, got: {content[:200]}"
