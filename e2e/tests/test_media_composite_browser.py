"""Playwright coverage for the `/media-composite` chromakey preview-tweak-save loop.

Uses a dedicated project + server (own fixtures below) rather than the shared
``lens_project_dir``/``live_server_url`` from ``e2e/conftest.py``, since it needs a
media mount with a chroma-keyed source image that the shared session-scoped
project doesn't have.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Generator

import cv2
import numpy as np
import pytest
import tomli_w

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project

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
            [sys.executable, "-W", "ignore", "-c", probe],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


_REPO = Path(__file__).resolve().parents[2]
_STATIC_BUILT = _REPO / "lens/server/static/index.html"
_EXTERNAL_SERVER = bool(os.environ.get("LENS_DEV_SERVER_URL"))

pytestmark = pytest.mark.skipif(
    not _chromium_available() or not _STATIC_BUILT.exists() or _EXTERNAL_SERVER,
    reason="Run 'poe build-ui' and 'playwright install chromium'; needs a local (non-external) server",
)

_PAGE_TIMEOUT_MS = 15000


def _synthetic_magenta_png(size: int = 200, square: int = 100) -> bytes:
    img = np.full((size, size, 3), (255, 0, 255), dtype=np.uint8)  # BGR magenta
    lo, hi = size // 2 - square // 2, size // 2 + square // 2
    img[lo:hi, lo:hi] = (0, 0, 0)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


# ---------------------------------------------------------------------------
# Fixtures: dedicated project + server (mount + chroma-keyed source image)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chromakey_llm_server() -> Generator[FakeLLMServer, None, None]:
    server = FakeLLMServer(stream_chunk_delay=0.05)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def chromakey_project_dir(
    chromakey_llm_server: FakeLLMServer,
) -> Generator[Path, None, None]:
    tmp = tempfile.mkdtemp(prefix="lens_e2e_chromakey_")
    project_dir = Path(tmp)
    setup_test_project(project_dir, chromakey_llm_server.base_url, narrative_name="story")

    lens_toml = project_dir / "lens.toml"
    with lens_toml.open("rb") as fh:
        cfg = tomllib.load(fh)
    cfg["project"]["mount_point"] = "media"
    with lens_toml.open("wb") as fh:
        tomli_w.dump(cfg, fh)

    media_dir = project_dir / "media"
    media_dir.mkdir(exist_ok=True)
    (media_dir / "hero.png").write_bytes(_synthetic_magenta_png())

    subprocess.run(["git", "add", "-A"], cwd=project_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture: chromakey media"],
        cwd=project_dir,
        capture_output=True,
        check=True,
    )
    yield project_dir
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def chromakey_server_url(chromakey_project_dir: Path) -> Generator[str, None, None]:
    import uvicorn

    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    session = ProjectSession(chromakey_project_dir, chromakey_project_dir)
    app = create_app({chromakey_project_dir.name: session})

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


@pytest.fixture(scope="module")
def chromakey_slug(chromakey_project_dir: Path) -> str:
    return chromakey_project_dir.name


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMediaCompositeChromakeyBrowser:
    def test_preview_tweak_save_loop(
        self,
        page: "Page",
        chromakey_server_url: str,
        chromakey_slug: str,
    ) -> None:
        page.goto(f"{chromakey_server_url}#{chromakey_slug}/story")  # type: ignore[union-attr]
        page.wait_for_selector('[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        # The command bar's known-command list only settles once /stats resolves,
        # slightly after markdown-view mounts — wait it out before typing a short command.
        page.wait_for_load_state("networkidle")  # type: ignore[union-attr]

        cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/media-composite chromakey hero.png")  # type: ignore[union-attr]
        page.keyboard.press("Enter")  # type: ignore[union-attr]

        overlay = page.locator('[role="dialog"][aria-label="Chromakey preview"]')  # type: ignore[union-attr]
        overlay.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]

        # Preview loaded: image visible, auto-resolved core tolerance echoed into the input box.
        page.wait_for_selector(".carousel-spotlight img", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        core_tol_input = page.locator('[data-testid="composite-core-tol-input"]')  # type: ignore[union-attr]
        page.wait_for_function(  # type: ignore[union-attr]
            "() => document.querySelector('[data-testid=\"composite-core-tol-input\"]')?.value !== ''",
            timeout=_PAGE_TIMEOUT_MS,
        )
        assert core_tol_input.input_value() != ""  # type: ignore[union-attr]

        # Chromeless toggle: same click-to-focus behavior on desktop and mobile
        # (no separate in-app zoom -- users zoom with native gestures from
        # here). Entering it hides the controls/actions rows, and there must
        # be a tap-friendly close button since Escape doesn't work on touch.
        overlay.locator(".composite-image-toggle").click()  # type: ignore[union-attr]
        page.wait_for_function(  # type: ignore[union-attr]
            "() => getComputedStyle(document.querySelector('.composite-controls')).display === 'none'",
            timeout=_PAGE_TIMEOUT_MS,
        )
        # Original pixel size, not scaled to fit -- a scaled-down image just
        # magnifies interpolated pixels once the user zooms, useless for
        # judging a chroma-key edge.
        img_max_width = page.locator(".carousel-spotlight img").evaluate(  # type: ignore[union-attr]
            "el => getComputedStyle(el).maxWidth"
        )
        assert img_max_width == "none"
        close_btn = overlay.locator(".composite-chromeless-close")  # type: ignore[union-attr]
        close_btn.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        # `fixed`, not `absolute` -- the latter scrolls away with the
        # now-oversized, natively-sized image inside .carousel-spotlight.
        assert close_btn.evaluate("el => getComputedStyle(el).position") == "fixed"  # type: ignore[union-attr]
        close_btn.click()  # type: ignore[union-attr]
        page.wait_for_function(  # type: ignore[union-attr]
            "() => getComputedStyle(document.querySelector('.composite-controls')).display !== 'none'",
            timeout=_PAGE_TIMEOUT_MS,
        )

        # Tweak tolerance and re-preview: the box should keep exactly what was typed, not an auto value.
        core_tol_input.fill("30")  # type: ignore[union-attr]
        page.get_by_role("button", name="Preview").click()  # type: ignore[union-attr]
        page.wait_for_function(  # type: ignore[union-attr]
            "() => document.querySelector('[data-testid=\"composite-core-tol-input\"]')?.value === '30'",
            timeout=_PAGE_TIMEOUT_MS,
        )

        # The Key box is populated from the auto-detected result too (not left blank).
        key_input = overlay.locator('input[aria-label="Key"]')  # type: ignore[union-attr]
        assert key_input.input_value() == "#FF00FF"  # type: ignore[union-attr]

        # Tooltips are tap/click-toggled (not hover-only, which doesn't fire on touch):
        # clicking the label reveals it, clicking elsewhere dismisses it.
        # Portaled to document.body (see InfoTooltip.svelte), so it's not a
        # descendant of `overlay` -- scope from `page`, not `overlay`.
        tip = page.locator(".info-tip")  # type: ignore[union-attr]
        assert tip.count() == 0  # type: ignore[union-attr]
        overlay.get_by_role("button", name="Core tol").click()  # type: ignore[union-attr]
        tip.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]

        # Regression: flex items paint as an implicit DOM-order stack, so a
        # non-portaled tooltip nested in an *earlier* field (Core tol) would
        # render fine but be visually painted UNDER a *later* sibling field's
        # plain input (Residual thresh), even at high z-index. Confirm the
        # tip -- not an input -- is topmost where they overlap.
        tip_box = tip.bounding_box()  # type: ignore[union-attr]
        overlap_point = [tip_box["x"] + tip_box["width"] - 10, tip_box["y"] + 5]  # type: ignore[index]
        topmost_class = page.evaluate(  # type: ignore[union-attr]
            "([x, y]) => document.elementFromPoint(x, y)?.className", overlap_point
        )
        assert "info-tip" in topmost_class

        # Opening a second tooltip closes the first -- they must not stack up.
        overlay.get_by_role("button", name="Residual thresh").click()  # type: ignore[union-attr]
        page.wait_for_function(  # type: ignore[union-attr]
            "() => document.querySelectorAll('.info-tip').length === 1",
            timeout=_PAGE_TIMEOUT_MS,
        )
        assert "alpha-blend" in tip.inner_text()  # type: ignore[union-attr]

        overlay.locator(".carousel-title").click()  # type: ignore[union-attr]
        assert tip.count() == 0  # type: ignore[union-attr]

        # Dilate px is hidden entirely -- a large value can peg the server CPU.
        assert overlay.get_by_role("button", name="Dilate px").count() == 0  # type: ignore[union-attr]

        # The destination filename is shown before saving.
        assert "hero_fg.png" in page.locator(".composite-saved-path").inner_text()  # type: ignore[union-attr]

        # Save: closes the whole panel once done -- nothing left to interact with.
        page.get_by_role("button", name="Save").click()  # type: ignore[union-attr]
        overlay.wait_for(state="hidden", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]

        # And the saved file is immediately visible when browsing -- the save route's
        # write must invalidate the same cache /mount/browse reads from.
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/media-composite chromakey")  # type: ignore[union-attr]
        page.keyboard.press("Enter")  # type: ignore[union-attr]
        carousel = page.locator('[role="dialog"][aria-label="Chromakey Source"]')  # type: ignore[union-attr]
        carousel.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        carousel.locator('.carousel-tile img[alt="hero_fg.png"]').wait_for(  # type: ignore[union-attr]
            state="visible", timeout=_PAGE_TIMEOUT_MS
        )

    def test_folder_browse_opens_carousel_and_closing_preview_returns_to_it(
        self,
        page: "Page",
        chromakey_server_url: str,
        chromakey_slug: str,
    ) -> None:
        """No image path (or a folder): browse for a source, exactly like media-attach.

        Selecting a file starts the preview instead of attaching it; closing the
        preview goes back to the carousel at the folder it was opened from.
        """
        page.goto(f"{chromakey_server_url}#{chromakey_slug}/story")  # type: ignore[union-attr]
        page.wait_for_selector('[data-testid="markdown-view"]', timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        # See test_preview_tweak_save_loop: the known-command list settles slightly
        # after markdown-view mounts, and this short command types fast enough to race it.
        page.wait_for_load_state("networkidle")  # type: ignore[union-attr]

        cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/media-composite chromakey")  # type: ignore[union-attr]
        page.keyboard.press("Enter")  # type: ignore[union-attr]

        carousel = page.locator('[role="dialog"][aria-label="Chromakey Source"]')  # type: ignore[union-attr]
        carousel.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]

        # Image tiles render only the thumbnail (no visible filename text), so match on alt text.
        carousel.locator('.carousel-tile img[alt="hero.png"]').click()  # type: ignore[union-attr]
        page.get_by_role("button", name="Chromakey").click()  # type: ignore[union-attr]

        overlay = page.locator('[role="dialog"][aria-label="Chromakey preview"]')  # type: ignore[union-attr]
        overlay.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        assert carousel.count() == 0
        assert "hero.png" in overlay.locator(".carousel-title").inner_text()  # type: ignore[union-attr]

        overlay.get_by_role("button", name="Close").click()  # type: ignore[union-attr]
        carousel.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        assert overlay.count() == 0
