"""Playwright: a trigger offer runs through the command bar, like the CLI (#195).

The offer's stored ``run`` is an ordinary command line. **Run** submits it and
**Edit** puts it in the bar; either way the next submission carries the slug, so
the session is ``<slug>-tr``. The ``run`` uses the CLI's own spelling — a bare
module key and a shell-quoted prompt — which the UI reads exactly as the CLI
does.

Dedicated project and server (own fixtures), because firing a trigger changes
the cursor for every later test on a shared project.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import pytest

from lens.testing.fake_llm import FakeLLMServer

if TYPE_CHECKING:
    from playwright.sync_api import Page


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


_REPO = Path(__file__).resolve().parents[2]
_STATIC_BUILT = _REPO / "lens/server/static/index.html"
_EXTERNAL_SERVER = bool(os.environ.get("LENS_DEV_SERVER_URL"))

pytestmark = pytest.mark.skipif(
    not _chromium_available() or not _STATIC_BUILT.exists() or _EXTERNAL_SERVER,
    reason="Run 'poe build-ui' and 'playwright install chromium'; needs a local server",
)

_PAGE_TIMEOUT_MS = 15000
_STREAM_TIMEOUT_MS = 60000

PREP = (
    "[\n"
    "    triggers:\n"
    "      design-cellar:\n"
    "        when: Enso opens the store cellar hatch\n"
    "        run: design --module person \"build the cellar\"\n"
    "      design-loft:\n"
    "        when: Enso climbs to the loft\n"
    "        run: design --module design.person \"build the loft\"\n"
    "]: #\n"
    "\n"
    "The village store.\n"
)


@pytest.fixture(scope="module")
def project_dir() -> Generator[Path, None, None]:
    from lens.core.pinning import pin
    from lens.testing.project import setup_test_project

    llm = FakeLLMServer()
    llm.start()
    tmp = Path(tempfile.mkdtemp(prefix="lens_e2e_trigger_"))
    session = setup_test_project(tmp, llm.base_url, opening_write=False)
    (tmp / "knowledge" / "prep").mkdir(parents=True, exist_ok=True)
    (tmp / "knowledge" / "prep" / "store.md").write_text(PREP)
    narrative = session.active_narrative
    assert narrative is not None
    storage = session.new_storage()
    pin(narrative, ["prep.store"], storage)
    md = narrative.md_path()
    md.write_text(
        md.read_text().rstrip("\n")
        + "\n\nEnso reaches the hatch.\n\n<!-- suggest:design-cellar -->\n"
        + "<!-- suggest:design-loft -->\n"
    )
    storage.stage_all()
    yield tmp
    llm.stop()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def server_url(project_dir: Path) -> Generator[str, None, None]:
    import uvicorn

    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    app = create_app({project_dir.name: ProjectSession(project_dir, project_dir)})
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
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


def _session_params(project_dir: Path, session_id: str) -> dict[str, object]:
    from lens.core.annotations import parse_annotations

    root = (project_dir / "narrative" / "story" / "_node.md").read_text()
    opened = [a for a in parse_annotations(root) if a.id == session_id and not a.closing]
    assert len(opened) == 1, root
    return opened[0].params


def _open(page: "Page", server_url: str, project_dir: Path) -> None:
    page.goto(f"{server_url}#{project_dir.name}/story")  # type: ignore[union-attr]
    page.wait_for_selector('[data-testid="cursor-offer-pills"]', timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]


def test_offers_render_at_the_cursor(page: "Page", server_url: str, project_dir: Path) -> None:
    _open(page, server_url, project_dir)
    offers = page.locator('[data-testid="cursor-offer"]')  # type: ignore[union-attr]
    assert offers.count() == 2
    assert "design-cellar" in offers.nth(0).inner_text()
    assert "Enso opens the store cellar hatch" in offers.nth(0).inner_text()


def test_edit_puts_the_cli_line_in_the_bar(page: "Page", server_url: str, project_dir: Path) -> None:
    _open(page, server_url, project_dir)
    offer = page.locator('[data-testid="cursor-offer"]').filter(has_text="design-loft")  # type: ignore[union-attr]
    offer.get_by_role("button", name="Edit").click()
    cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
    page.wait_for_function(  # type: ignore[union-attr]
        "() => document.querySelector('[data-testid=\"cli-input\"]').value.startsWith('/design')",
        timeout=_PAGE_TIMEOUT_MS,
    )
    assert cli.input_value() == '/design --module design.person "build the loft"'


def test_run_fires_it_with_cli_semantics(page: "Page", server_url: str, project_dir: Path) -> None:
    _open(page, server_url, project_dir)
    offer = page.locator('[data-testid="cursor-offer"]').filter(has_text="design-cellar")  # type: ignore[union-attr]
    offer.get_by_role("button", name="Run").click()
    child = project_dir / "narrative" / "story" / "design-cellar-tr.md"
    deadline = time.time() + _STREAM_TIMEOUT_MS / 1000
    # The child exists as soon as the session opens; wait for the generated block.
    while time.time() < deadline and not (child.exists() and "[/design]: #" in child.read_text()):
        time.sleep(0.2)
    assert child.exists(), "Run did not open design-cellar-tr"
    params = _session_params(project_dir, "design-cellar-tr")
    assert params["module"] == "person"  # bare key, as the CLI accepts it
    assert params["trigger"] == "design-cellar"
    # Shell-quoted prompt arrives unquoted, as the shell would pass it.
    child_text = child.read_text()
    assert "prompt: build the cellar" in child_text, child_text
