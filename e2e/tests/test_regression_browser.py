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


def _run_cli_command(page: "Page", text: str) -> None:
    """Type *text* into the CLI and submit it, once the CLI can accept commands.

    The command registry is built from the first ``/stats`` response, so an
    Enter that lands before it does is rejected as an unknown command and
    silently swallowed.  The cursor context pill renders only from applied
    stats, so waiting for it proves the registry is populated.
    """
    page.wait_for_selector(
        '[data-testid="cursor-context-explain"]', timeout=_PAGE_TIMEOUT_MS
    )
    cli = page.locator('[data-testid="cli-input"]')
    cli.click()
    cli.press_sequentially(text)
    page.keyboard.press("Enter")


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

        _run_cli_command(page, "/write begin ")

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

        _run_cli_command(page, "/structure-explain")

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


class TestRegressionPendingKbBrowser:
    """PW-09: a session's KB writes are visible to the person, not only the model.

    Since the KB verbs replaced the fenced ``kb`` blocks, what a ``design`` or
    ``advance`` beat changes lives in ``[kb-op …]: #`` markdown comments — which
    every renderer in the stack hides on purpose.  The reader was left watching
    the model *say* it updated an object with no way to check.  This walks the
    places that answer that: the split chip where the block sits, the block
    itself behind the chip's body half, the diff in the KB viewer, and the
    bullets in the cursor footer.
    """

    _PROPOSALS = """
[design
  prompt: session zero
]: #

The warden now holds the ford, and Amy's file needs a line I cannot place.

[kb-op
  op: add
  id: npc.warden
  body: |
    | # The Warden
    | Grim, and fair.
]: #

[kb-op
  op: patch
  id: person.amy
  patches: [{"start": {"target": "NO SUCH LINE IN AMY"}, "content": " x"}]
]: #
"""

    # A closed session: the child keeps its blocks but the cursor has moved on,
    # so there is no pending layer and no `pending_kb` in the payload.  The
    # chips still have to work — that is the whole reason they are parsed from
    # the block text rather than from the payload.
    _HISTORY = """[
  kb_pin: []
]: #

I set the warden at the ford.

[kb-op
  op: tag
  id: npc.warden
  tags:
    - ford
  remove-tags:
    - draft
]: #
"""

    def test_pw09_proposals_are_visible_in_all_three_places(
        self,
        page: "Page",
        live_server_url: str,
        lens_project_dir: Path | None,
        project_slug: str,
    ) -> None:
        if lens_project_dir is None:
            pytest.skip("Requires local project dir")

        cursor_md = lens_project_dir / "narrative" / "story" / "_node.md"
        original = cursor_md.read_text()
        try:
            cursor_md.write_text(original + self._PROPOSALS)

            # The node route serves proposals only for the cursor, so this is
            # also the check that the layer and the payload agree about where
            # the cursor is.
            with urllib.request.urlopen(
                f"{live_server_url}/{project_slug}/narrative/node/story", timeout=10
            ) as response:
                payload = json.load(response)
            pending = payload["pending_kb"]
            assert [op["op"] for op in pending["ops"]] == ["add", "patch"]
            assert pending["ops"][1]["status"] == "error"

            page.goto(f"{live_server_url}#{project_slug}/story")  # type: ignore[union-attr]
            page.wait_for_selector(  # type: ignore[union-attr]
                '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
            )

            # 1. A chip per op, in place, where the block was consumed — and
            #    none of the block's own text, which is what the model reads.
            chips = page.locator(".kb-op-marker")  # type: ignore[union-attr]
            chips.first.wait_for(timeout=_PAGE_TIMEOUT_MS)
            assert chips.count() == 2
            assert page.locator(".kb-op-marker--error").count() == 1  # type: ignore[union-attr]
            body = page.inner_text('[data-testid="markdown-view"]')  # type: ignore[union-attr]
            assert "patches:" not in body
            assert "Grim, and fair." not in body

            # 2. The footer lists the changed object beside the pins.
            bullets = page.locator(  # type: ignore[union-attr]
                '[data-testid="cursor-pending-kb-pills"] .pin-pill--pending'
            )
            bullets.first.wait_for(timeout=_PAGE_TIMEOUT_MS)
            assert "npc.warden" in bullets.first.inner_text()

            # 3. The body half opens the block as written — the intent, which
            #    is readable whether or not there is still a diff to be had.
            warden = page.locator(  # type: ignore[union-attr]
                '.kb-op-marker:has([data-kb-open-id="npc.warden"]) .kb-op-marker-body'
            )
            warden.click()
            page.wait_for_selector(".kb-op-dialog[open]", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
            modal = page.inner_text(".kb-op-dialog")  # type: ignore[union-attr]
            assert "Grim, and fair." in modal
            assert "npc.warden" in modal
            # At the cursor it is still a proposal, so the modal may say so.
            assert "PROPOSED" in modal.upper()
            assert "hand-edit" in modal
            page.keyboard.press("Escape")  # type: ignore[union-attr]
            page.wait_for_selector(  # type: ignore[union-attr]
                ".kb-op-dialog[open]", state="hidden", timeout=_PAGE_TIMEOUT_MS
            )

            # 4. The arrow half opens the object, with the proposed change
            #    against its base shown inline — no modal in the path.
            page.click('.kb-op-marker-open[data-kb-open-id="npc.warden"]')  # type: ignore[union-attr]
            page.wait_for_selector(  # type: ignore[union-attr]
                '[data-testid="kb-pending-diff"]', timeout=_PAGE_TIMEOUT_MS
            )
            diff = page.inner_text('[data-testid="kb-pending-diff"]')  # type: ignore[union-attr]
            assert "Grim, and fair." in diff
            assert page.locator(".kb-pending-line--insert").count() > 0  # type: ignore[union-attr]
            assert page.locator(".kb-diff-dialog[open]").count() == 0  # type: ignore[union-attr]
        finally:
            cursor_md.write_text(original)

    def test_pw09b_a_historical_node_still_shows_what_the_beat_asked_for(
        self,
        page: "Page",
        live_server_url: str,
        lens_project_dir: Path | None,
        project_slug: str,
    ) -> None:
        if lens_project_dir is None:
            pytest.skip("Requires local project dir")

        aside = lens_project_dir / "narrative" / "story" / "aside.md"
        try:
            aside.write_text(self._HISTORY)

            with urllib.request.urlopen(
                f"{live_server_url}/{project_slug}/narrative/node/story/aside", timeout=10
            ) as response:
                payload = json.load(response)
            assert "pending_kb" not in payload

            page.goto(f"{live_server_url}#{project_slug}/story/aside")  # type: ignore[union-attr]
            page.wait_for_selector(  # type: ignore[union-attr]
                '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
            )
            page.wait_for_selector(".kb-op-marker", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
            page.click(".kb-op-marker-body")  # type: ignore[union-attr]
            page.wait_for_selector(".kb-op-dialog[open]", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
            modal = page.inner_text(".kb-op-dialog")  # type: ignore[union-attr]
            assert "+ford" in modal
            assert "-draft" in modal
            # Nothing is pending here, so nothing may invite the reader to
            # hand-edit a block that no longer feeds anything.
            assert "WRITTEN" in modal.upper()
            assert "hand-edit" not in modal
            assert page.locator(".kb-op-marker--recorded").count() > 0  # type: ignore[union-attr]
            assert page.locator(".kb-op-marker--pending").count() == 0  # type: ignore[union-attr]
            page.keyboard.press("Escape")  # type: ignore[union-attr]

            # No proposals here, so nothing that speaks for the pending layer.
            assert page.locator('[data-testid="kb-pending-diff"]').count() == 0  # type: ignore[union-attr]
            assert page.locator(  # type: ignore[union-attr]
                '[data-testid="cursor-pending-kb-pills"]'
            ).count() == 0
        finally:
            aside.unlink(missing_ok=True)

    def test_pw09c_nothing_shows_without_proposals(
        self,
        page: "Page",
        live_server_url: str,
        lens_project_dir: Path | None,
        project_slug: str,
    ) -> None:
        if lens_project_dir is None:
            pytest.skip("Requires local project dir")

        page.goto(f"{live_server_url}#{project_slug}/story")  # type: ignore[union-attr]
        page.wait_for_selector(  # type: ignore[union-attr]
            '[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS
        )
        assert page.locator(".kb-op-marker").count() == 0  # type: ignore[union-attr]
        assert page.locator(  # type: ignore[union-attr]
            '[data-testid="cursor-pending-kb-pills"]'
        ).count() == 0
