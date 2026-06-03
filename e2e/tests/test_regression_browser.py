"""Playwright regression cases (PW-*) for workflow UI."""

from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

_REPO = Path(__file__).resolve().parents[2]
_STATIC_BUILT = _REPO / "lens/server/static/index.html"

_PAGE_TIMEOUT_MS = 15000
_STREAM_TIMEOUT_MS = 60000


def _chromium_available() -> bool:
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
    not _chromium_available() or not _STATIC_BUILT.exists(),
    reason="Run 'poe build-ui' and 'playwright install chromium' first",
)


class TestRegressionWorkflowBrowser:
    """PW-01: workflow step strip visible during /write stream."""

    def test_pw01_write_shows_workflow_steps(
        self,
        page: "Page",
        live_server_url: str,
        project_slug: str,
    ) -> None:
        page.goto(f"{live_server_url}#{project_slug}/story")  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        rollback_req = urllib.request.Request(
            f"{live_server_url}/{project_slug}/rollback",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(rollback_req, timeout=10):
            pass

        cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/write begin ")
        page.keyboard.press("Enter")  # type: ignore[union-attr]

        page.wait_for_selector(
            '[data-testid="workflow-steps"]',
            timeout=_STREAM_TIMEOUT_MS,
        )  # type: ignore[union-attr]
        steps = page.locator('[data-testid="workflow-step"]')  # type: ignore[union-attr]
        assert steps.count() >= 1
        labels = steps.locator(".workflow-step-label").all_inner_texts()
        assert any("Generating" in label for label in labels)

    def test_pw06_transaction_diff_still_renders(
        self,
        page: "Page",
        live_server_url: str,
        lens_project_dir: Path | None,
        project_slug: str,
    ) -> None:
        """PW-06: delegate to existing transaction diff coverage."""
        if lens_project_dir is None:
            pytest.skip("Requires local project dir")
        from e2e.tests.test_browser import TestBrowser

        TestBrowser().test_transaction_diff_rendering(
            page, live_server_url, lens_project_dir, project_slug
        )
