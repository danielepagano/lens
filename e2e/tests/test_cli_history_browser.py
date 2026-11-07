"""Playwright: Up/Down history in the command bar never loses what was typed.

History reads like one continuous text, as in Claude Code: every Up/Down
moves one visual line (soft wraps count), crossing into the older entry's last
line or the newer entry's first line at the same column. Leaving the draft for
a history entry keeps it, and Down past the newest entry (or Escape) brings it
back. Caret geometry needs real layout, which is why this is a browser test.

History is seeded through localStorage and nothing is submitted, so the shared
session project and server are safe to use.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


def _chromium_available() -> bool:
    probe = (
        "from playwright.sync_api import sync_playwright;"
        "p=sync_playwright().__enter__();"
        "import sys, pathlib;"
        "sys.exit(0 if pathlib.Path(p.chromium.executable_path).exists() else 1)"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-W", "ignore", "-c", probe], capture_output=True, timeout=15
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


_STATIC_BUILT = pathlib.Path(__file__).parent.parent.parent / "lens/server/static/index.html"

pytestmark = pytest.mark.skipif(
    not _chromium_available() or not _STATIC_BUILT.exists(),
    reason="Run 'poe build-ui' and 'playwright install chromium' first",
)

_PAGE_TIMEOUT_MS = 5000
_HISTORY = ["/kb get rules.system", "/explain"]
_LONG_DRAFT = "/write " + " ".join(["a long half-written instruction"] * 12)


def _open_cli(
    page: "Page", live_server_url: str, project_slug: str, history: list[str] = _HISTORY
) -> "Locator":
    page.set_viewport_size({"width": 800, "height": 800})
    page.add_init_script(
        f"localStorage.setItem('lens.cli.history', {json.dumps(json.dumps(history))})"
    )
    page.goto(f"{live_server_url}#{project_slug}/story")
    page.wait_for_selector('[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS)
    cli = page.locator('[data-testid="cli-input"]')
    cli.click()
    return cli


def _caret(cli: "Locator") -> int:
    return int(cli.evaluate("el => el.selectionStart"))


class TestCliHistoryBrowser:
    def test_draft_survives_browsing_history(
        self, page: "Page", live_server_url: str, project_slug: str
    ) -> None:
        cli = _open_cli(page, live_server_url, project_slug)
        cli.fill("/write my draft")

        cli.press("ArrowUp")
        assert cli.input_value() == "/explain"
        cli.press("ArrowUp")
        assert cli.input_value() == "/kb get rules.system"
        cli.press("ArrowUp")  # oldest: stays put
        assert cli.input_value() == "/kb get rules.system"

        cli.press("ArrowDown")
        assert cli.input_value() == "/explain"
        cli.press("ArrowDown")
        assert cli.input_value() == "/write my draft"
        cli.press("ArrowDown")  # already on the draft: nothing is cleared
        assert cli.input_value() == "/write my draft"

    def test_browsing_keeps_the_caret_column(
        self, page: "Page", live_server_url: str, project_slug: str
    ) -> None:
        cli = _open_cli(page, live_server_url, project_slug)
        cli.fill("/write my draft")
        cli.evaluate("el => el.setSelectionRange(4, 4)")
        cli.press("ArrowUp")
        assert cli.input_value() == "/explain"
        assert _caret(cli) == 4
        cli.press("ArrowUp")
        assert _caret(cli) == 4
        cli.press("ArrowDown")
        cli.press("ArrowDown")
        assert cli.input_value() == "/write my draft"
        assert _caret(cli) == 4

    def test_escape_returns_to_the_draft(
        self, page: "Page", live_server_url: str, project_slug: str
    ) -> None:
        cli = _open_cli(page, live_server_url, project_slug)
        cli.fill("/write my draft")
        cli.press("ArrowUp")
        cli.press("ArrowUp")
        assert cli.input_value() == "/kb get rules.system"
        cli.press("Escape")
        assert cli.input_value() == "/write my draft"

    def test_wrapped_input_moves_caret_before_browsing(
        self, page: "Page", live_server_url: str, project_slug: str
    ) -> None:
        cli = _open_cli(page, live_server_url, project_slug)
        cli.fill(_LONG_DRAFT)
        height = cli.evaluate("el => el.clientHeight")
        line = cli.evaluate("el => parseFloat(getComputedStyle(el).lineHeight)")
        assert height > line * 1.5, "the draft should wrap onto several lines"

        # From the end, Up walks the caret up through the wrapped lines first.
        presses = 0
        while cli.input_value() == _LONG_DRAFT:
            before = _caret(cli)
            cli.press("ArrowUp")
            presses += 1
            assert presses < 20, "Up never reached history"
            if cli.input_value() == _LONG_DRAFT:
                assert _caret(cli) < before
        assert presses >= 2
        assert cli.input_value() == "/explain"

        # Down past the newest entry restores the wrapped draft untouched.
        cli.press("ArrowDown")
        assert cli.input_value() == _LONG_DRAFT

        # Caret mid-draft on the first line: Down moves within the draft, never into history.
        cli.evaluate("el => el.setSelectionRange(3, 3)")
        cli.press("ArrowDown")
        assert cli.input_value() == _LONG_DRAFT
        assert _caret(cli) > 3

    def test_up_onto_a_wrapped_entry_walks_its_lines(
        self, page: "Page", live_server_url: str, project_slug: str
    ) -> None:
        history = ["/explain", _LONG_DRAFT, "/kb get rules.system"]
        cli = _open_cli(page, live_server_url, project_slug, history)
        cli.fill("/write my draft")
        cli.press("ArrowUp")
        cli.press("ArrowUp")
        assert cli.input_value() == _LONG_DRAFT
        # Landed on the entry's last line: the next Ups climb it before going older.
        landed = _caret(cli)
        assert landed > len(_LONG_DRAFT) // 2
        presses = 0
        while cli.input_value() == _LONG_DRAFT:
            before = _caret(cli)
            cli.press("ArrowUp")
            presses += 1
            assert presses < 20, "Up never left the wrapped entry"
            if cli.input_value() == _LONG_DRAFT:
                assert _caret(cli) < before
        assert presses >= 2
        assert cli.input_value() == "/explain"

        # Down comes back onto the wrapped entry's first line.
        cli.press("ArrowDown")
        assert cli.input_value() == _LONG_DRAFT
        assert _caret(cli) < 20
