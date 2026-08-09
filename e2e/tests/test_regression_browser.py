"""Playwright regression cases (PW-*) for workflow UI."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
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

    def test_pw07_explain_modal_reports_composition(
        self,
        page: "Page",
        live_server_url: str,
        project_slug: str,
    ) -> None:
        """PW-07: the context report opens from the cursor and reconciles."""
        page.goto(f"{live_server_url}#{project_slug}/story")  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        page.click('[data-testid="cursor-context-explain"]')  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="explain-totals"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        # The API is the source of truth; the modal must not invent or drop blocks.
        with urllib.request.urlopen(
            f"{live_server_url}/{project_slug}/explain", timeout=10
        ) as response:
            report = json.load(response)
        expected_blocks = [b["id"] for b in report["blocks"]]
        assert expected_blocks, "explain returned no blocks"

        sections = page.locator('[data-testid="explain-block"]')  # type: ignore[union-attr]
        assert [
            sections.nth(i).get_attribute("data-block") for i in range(sections.count())
        ] == expected_blocks

        # Empty blocks are dropped from the bar but still get a section, so the
        # bar can have fewer segments than blocks — never more.
        segments = page.locator('[data-testid="explain-bar-segment"]')  # type: ignore[union-attr]
        assert 0 < segments.count() <= len(expected_blocks)

        title = page.inner_text('[data-testid="explain-title"]')  # type: ignore[union-attr]
        assert report["operator"] in title

        # Every component the report lists is rendered as a row.
        expected_rows = sum(len(b["components"]) for b in report["blocks"])
        assert page.locator('[data-testid="explain-row"]').count() >= expected_rows  # type: ignore[union-attr]

        # A modal dialog blocks the rest of the page, so leave it closed.
        page.click(".explain-close")  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="explain-modal"]', state="hidden", timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

    def test_pw08_explain_opens_from_cli_command(
        self,
        page: "Page",
        live_server_url: str,
        project_slug: str,
    ) -> None:
        """PW-08: `/structure-explain` opens the same modal from anywhere."""
        page.goto(f"{live_server_url}#{project_slug}/story")  # type: ignore[union-attr]
        # A hash-only navigation does not reload, so an earlier case can leave
        # the CLI mid-stream (and therefore busy). Reload for a clean client.
        cancel_req = urllib.request.Request(
            f"{live_server_url}/{project_slug}/stream/cancel", data=b"", method="POST"
        )
        try:
            with urllib.request.urlopen(cancel_req, timeout=10):
                pass
        except urllib.error.HTTPError:
            pass
        page.reload()  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/structure-explain")
        page.keyboard.press("Enter")  # type: ignore[union-attr]

        page.wait_for_selector(
            '[data-testid="explain-totals"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        assert page.locator('[data-testid="explain-block"]').count() >= 1  # type: ignore[union-attr]

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
