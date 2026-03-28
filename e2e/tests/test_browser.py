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

import asyncio
import contextlib
import io
import pathlib
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lens.core.operators.edit import EditOperator
from lens.core.project import ProjectSession

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

_PAGE_TIMEOUT_MS = 5000

pytestmark = pytest.mark.skipif(
    not _chromium_available() or not _STATIC_BUILT.exists(),
    reason="Run 'poe build-ui' and 'playwright install chromium' first",
)


class TestBrowser:
    """UI tests exercising the Lens frontend via a real browser."""

    def test_page_loads(self, page: "Page", live_server_url: str) -> None:
        """The root page loads and renders the top bar and tree browser."""
        page.goto(live_server_url)  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="top-bar"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="tree-browser"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        assert page.is_visible('[data-testid="top-bar"]')  # type: ignore[union-attr]
        assert page.is_visible('[data-testid="tree-browser"]')  # type: ignore[union-attr]

    def test_tree_has_nodes(self, page: "Page", live_server_url: str) -> None:
        """The tree browser renders; it may be empty if the active narrative has no children."""
        page.goto(live_server_url)  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="tree-browser"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        assert page.is_visible('[data-testid="tree-browser"]')  # type: ignore[union-attr]

    def test_node_navigation(self, page: "Page", live_server_url: str) -> None:
        """Navigating to #story loads Lorem ipsum content in MarkdownView."""
        page.goto(f"{live_server_url}#story")  # type: ignore[union-attr]
        page.locator('[data-testid="markdown-view"]').get_by_text("Lorem").wait_for(
            timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        content: str = page.inner_text('[data-testid="markdown-view"]')  # type: ignore[union-attr]
        assert "Lorem" in content, f"Expected Lorem ipsum in markdown view, got: {content[:200]}"

    def test_transaction_diff_rendering(
        self,
        page: "Page",
        live_server_url: str,
        lens_project_dir: Path | None,
    ) -> None:
        """Pending edit transaction for #story is rendered as green additions and red removals."""
        if lens_project_dir is None:
            pytest.skip("Requires local project dir; not supported in external-server mode")

        session = ProjectSession(lens_project_dir, lens_project_dir)
        narrative = session.active_narrative
        assert narrative is not None

        node = narrative
        md_path = node.md_path()

        # Overwrite the root node with simple, deterministic content and commit it as baseline.
        md_path.write_text("Line one.\nLine two.\n")
        subprocess.run(
            ["git", "add", "-A"],
            cwd=lens_project_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "baseline for transaction diff"],
            cwd=lens_project_dir,
            capture_output=True,
            check=True,
        )

        rel_path = str(md_path.relative_to(lens_project_dir).as_posix())
        ann_id = EditOperator.ann_id(2, 2)

        # Create a pending manual edit transaction replacing line 2.
        def _run() -> None:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                asyncio.run(
                    EditOperator.run_mutation(
                        session=session,
                        node=node,
                        rel_path=rel_path,
                        ann_id=ann_id,
                        start_line=2,
                        end_line=2,
                        prompt="Replacement line two.",
                        manual=True,
                        pins=[],
                        unpins=[],
                        llm_id=None,
                        retry=False,
                    )
                )

        t = threading.Thread(target=_run)
        t.start()
        t.join()

        page.goto(f"{live_server_url}#story")  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        view = page.locator('[data-testid="markdown-view"]')  # type: ignore[union-attr]

        added = view.locator(".transaction-added").filter(has_text="Replacement line two.")
        removed = view.locator(".transaction-removed").filter(has_text="Line two.")

        added.first.wait_for(timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        removed.first.wait_for(timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]

        assert "Replacement line two." in added.first.inner_text()
        assert "Line two." in removed.first.inner_text()

        html = view.inner_html()
        idx_removed = html.find("transaction-removed")
        idx_replacement = html.find("Replacement line two.")
        assert idx_removed >= 0 and idx_replacement >= 0
        assert idx_removed < idx_replacement, (
            "Expected .transaction-removed to appear before the replacement text in the DOM"
        )

    def test_edit_line_slot_shows_line_picker_not_markdown_preview(
        self,
        page: "Page",
        live_server_url: str,
    ) -> None:
        """Typing `/edit / ` leaves the `start` line slot active: line-picker UI, no rendered MD.

        This asserts the valueType ``line`` path in ``Cli.svelte`` + ``MarkdownView``: the
        main pane switches from ``.markdown-html-root`` to ``[data-testid="line-picker"]``.

        The ``edit --replace`` narrative UX is tracked separately (see
        ``test_edit_replace_after_line_pick_shows_inline_codemirror``).
        """
        page.goto(f"{live_server_url}#story")  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        page.locator('[data-testid="markdown-view"] .markdown-html-root').wait_for(
            timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/edit / ")

        page.wait_for_selector(
            '[data-testid="markdown-view"] [data-testid="line-picker"]',
            timeout=10000,
        )  # type: ignore[union-attr]
        assert page.locator('[data-testid="line-picker"]').is_visible()  # type: ignore[union-attr]
        assert page.locator('[data-testid="markdown-view"] .markdown-html-root').count() == 0

    def test_edit_replace_after_line_pick_shows_inline_codemirror(
        self,
        page: "Page",
        live_server_url: str,
    ) -> None:
        """After `/edit / `, two line picks, ``--replace``, **Space** (not Enter), inline CodeMirror must mount."""
        page.goto(f"{live_server_url}#story")  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        page.locator('[data-testid="markdown-view"] .markdown-html-root').wait_for(
            timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/edit / ")

        page.wait_for_selector(
            '[data-testid="line-picker"]', timeout=10000
        )  # type: ignore[union-attr]
        pickable = page.locator(
            '[data-testid="line-picker"] .cm-line.cm-linepick-pickable'
        )  # type: ignore[union-attr]
        pickable.first.click()  # type: ignore[union-attr]

        page.wait_for_selector(
            '[data-testid="line-picker"]', timeout=10000
        )  # type: ignore[union-attr]
        pickable.first.click()  # type: ignore[union-attr]

        cli.press_sequentially("--replace")
        page.keyboard.press("Space")

        page.wait_for_selector(
            '[data-testid="inline-edit-view"]', state="visible", timeout=8000
        )  # type: ignore[union-attr]
        assert page.locator('[data-testid="inline-edit-view"] .cm-editor').count() >= 1

    def test_edit_replace_full_command_no_line_picker(
        self,
        page: "Page",
        live_server_url: str,
    ) -> None:
        """``/edit / <start> <end> --replace`` as one string, then **Space** (not Enter)."""
        page.goto(f"{live_server_url}#story")  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        page.locator('[data-testid="markdown-view"] .markdown-html-root').wait_for(
            timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/edit / 13 15 --replace")
        page.keyboard.press("Space")

        page.wait_for_selector(
            '[data-testid="inline-edit-view"]', state="visible", timeout=8000
        )  # type: ignore[union-attr]
        assert page.locator('[data-testid="inline-edit-view"] .cm-editor').count() >= 1

    def test_kb_editor_edit_append_and_save_persists(
        self,
        page: "Page",
        live_server_url: str,
    ) -> None:
        """KB viewer: open an item, Edit, change body text, Save — change must appear after save.

        Uses the throwaway e2e project from ``setup_test_project`` (``person.amy`` with a known
        baseline line). Flow matches manual use: KB mode → filter by type → pick item → Edit →
        type in CodeMirror → Save → read-only markdown view should include the appended text.

        If typing does not update bound state or Save does not persist, this test fails.
        """
        marker = " [[e2e-kb-editor-append]]"
        page.set_viewport_size({"width": 1280, "height": 720})  # type: ignore[union-attr]
        # Full reload to clear stale client state from earlier tests.
        page.goto(f"{live_server_url}#story", wait_until="networkidle")  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="top-bar"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        page.get_by_role("button", name="KB").click()  # type: ignore[union-attr]
        page.wait_for_selector(
            '[data-testid="kb-browser"]', timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        type_select = page.locator(
            '[data-testid="kb-browser"] select.kb-type-select'
        )  # type: ignore[union-attr]
        type_select.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        page.wait_for_function(
            """() => {
              const s = document.querySelector(
                '[data-testid="kb-browser"] select.kb-type-select'
              );
              return (
                s !== null &&
                Array.from((s).options).some((o) => o.value === 'person')
              );
            }""",
            timeout=15000,
        )  # type: ignore[union-attr]
        type_select.select_option("person")  # type: ignore[union-attr]
        amy_btn = page.locator("button.kb-item-btn").filter(has_text="amy")  # type: ignore[union-attr]
        amy_btn.wait_for(timeout=10000)  # type: ignore[union-attr]
        amy_btn.click()  # type: ignore[union-attr]

        viewer = page.locator(".kb-viewer")  # type: ignore[union-attr]
        viewer.locator(".kb-viewer-id").filter(has_text="person.amy").wait_for(
            timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]
        viewer.get_by_text("Amy is the brave protagonist.", exact=False).wait_for(
            timeout=_PAGE_TIMEOUT_MS
        )  # type: ignore[union-attr]

        viewer.get_by_role("button", name="Edit", exact=True).click()  # type: ignore[union-attr]
        cm_content = viewer.locator(".cm-content")  # type: ignore[union-attr]
        cm_content.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        cm_content.click()  # type: ignore[union-attr]
        page.keyboard.press("ControlOrMeta+End")  # type: ignore[union-attr]
        page.keyboard.type(marker)  # type: ignore[union-attr]

        viewer.get_by_role("button", name="Save").click()  # type: ignore[union-attr]
        viewer.locator(".kb-rendered").wait_for(
            state="visible", timeout=10000
        )  # type: ignore[union-attr]
        page.locator(".kb-viewer .cm-content").wait_for(state="detached", timeout=10000)  # type: ignore[union-attr]

        saved_text = viewer.locator(".kb-rendered").inner_text()  # type: ignore[union-attr]
        assert marker.strip() in saved_text, (
            f"Expected appended marker in KB read view after save; got excerpt: {saved_text[:400]!r}"
        )
        assert viewer.locator(".kb-save-error").count() == 0
