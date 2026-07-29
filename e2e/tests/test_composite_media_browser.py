"""Playwright coverage for bg/fg media compositing (issue #99, layered rendering).

Verifies the scaling contract in two rendering paths:

* **VN mode** (``VnStageMedia.svelte``, ``.vn-layered-wrap``/``.vn-layer-bg``/``.vn-layer-fg``):
  both layers scale to the same height (never cropped top/bottom), centered
  horizontally, cropping or gapping only on the sides as the frame reshapes.
* **Plain narrative preview** (non-VN reading mode, ``app.css`` ``.lens-vn-composite``):
  same contract — bg defines the box, fg matched to that height, centered.

Uses a dedicated project + server (own fixtures below) rather than the shared
``lens_project_dir``/``live_server_url`` from ``e2e/conftest.py``, since it needs a
media mount and composite embeds that the shared session-scoped project doesn't have.
Skipped when running against an external dev server (``LENS_DEV_SERVER_URL``), same
as ``test_transaction_diff_rendering`` in ``test_browser.py``.
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
from typing import TYPE_CHECKING, Any, Generator

import pytest

from e2e.fixtures.helpers import setup_composite_media_project
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

_IMAGES_LOADED_JS = (
    "(sel) => Array.from(document.querySelectorAll(sel))"
    ".every(img => img.complete && img.naturalWidth > 0)"
)

_LAYER_RECTS_JS = """() => {
  const r = (el) => {
    const b = el.getBoundingClientRect();
    return { left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width, height: b.height };
  };
  const wrap = document.querySelector('.vn-layered-wrap');
  const bg = document.querySelector('.vn-layer-bg');
  const fg = document.querySelector('.vn-layer-fg');
  return { wrap: r(wrap), bg: r(bg), fg: r(fg) };
}"""

_PLAIN_RECTS_JS = """() => {
  const r = (el) => {
    const b = el.getBoundingClientRect();
    return { left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width, height: b.height };
  };
  const box = document.querySelector('.lens-vn-composite');
  const bg = document.querySelector('.lens-vn-composite .lens-vn-bg');
  const fg = document.querySelector('.lens-vn-composite .lens-vn-fg');
  return { box: r(box), bg: r(bg), fg: r(fg) };
}"""

_TOL = 1.5  # px tolerance for sub-pixel layout rounding


# ---------------------------------------------------------------------------
# Fixtures: dedicated project + server (mount + composite scenes)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def composite_llm_server() -> Generator[FakeLLMServer, None, None]:
    server = FakeLLMServer(stream_chunk_delay=0.05)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def composite_project_dir(
    composite_llm_server: FakeLLMServer,
) -> Generator[Path, None, None]:
    tmp = tempfile.mkdtemp(prefix="lens_e2e_composite_")
    project_dir = Path(tmp)
    setup_composite_media_project(project_dir, composite_llm_server.base_url)
    yield project_dir
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def composite_server_url(composite_project_dir: Path) -> Generator[str, None, None]:
    import uvicorn

    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    session = ProjectSession(composite_project_dir, composite_project_dir)
    app = create_app({composite_project_dir.name: session})

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
def composite_slug(composite_project_dir: Path) -> str:
    return composite_project_dir.name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _goto_vn(page: "Page", server_url: str, slug: str, node: str) -> None:
    page.goto(f"{server_url}#{slug}/story/{node}?vn=1&vn_i=0&vn_spk=0")  # type: ignore[union-attr]
    page.wait_for_selector(".vn-layered-wrap", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
    page.wait_for_function(  # type: ignore[union-attr]
        _IMAGES_LOADED_JS, arg=".vn-layer-bg, .vn-layer-fg", timeout=_PAGE_TIMEOUT_MS
    )


def _assert_layered_wrap_contract(rects: dict[str, dict[str, Any]]) -> None:
    """Both layers span the wrap's full height (no top/bottom crop) and are centered."""
    wrap, bg, fg = rects["wrap"], rects["bg"], rects["fg"]
    for layer, name in ((bg, "bg"), (fg, "fg")):
        assert abs(layer["top"] - wrap["top"]) < _TOL, f"{name} top-cropped: {layer} vs wrap {wrap}"
        assert abs(layer["bottom"] - wrap["bottom"]) < _TOL, (
            f"{name} bottom-cropped: {layer} vs wrap {wrap}"
        )
        assert abs(layer["height"] - wrap["height"]) < _TOL, (
            f"{name} height mismatch (not in registration): {layer} vs wrap {wrap}"
        )
        wrap_center = (wrap["left"] + wrap["right"]) / 2
        layer_center = (layer["left"] + layer["right"]) / 2
        assert abs(wrap_center - layer_center) < _TOL, (
            f"{name} not horizontally centered: {layer} vs wrap {wrap}"
        )


class TestVnLayeredRendering:
    """VN mode: .vn-layered-wrap / .vn-layer-bg / .vn-layer-fg (VnStageMedia.svelte)."""

    @pytest.mark.parametrize("node", ["vn-combo-a", "vn-combo-b"])
    @pytest.mark.parametrize("width", [360, 1400])
    def test_layers_full_height_no_crop_centered(
        self,
        page: "Page",
        composite_server_url: str,
        composite_slug: str,
        node: str,
        width: int,
    ) -> None:
        """At narrow and wide viewport widths, bg/fg stay full-height, centered, in registration.

        ``vn-combo-a`` = landscape bg + portrait fg; ``vn-combo-b`` = portrait bg +
        landscape fg — the two orientation-mismatch directions called out in issue #99.
        """
        page.set_viewport_size({"width": width, "height": 800})  # type: ignore[union-attr]
        _goto_vn(page, composite_server_url, composite_slug, node)
        rects = page.evaluate(_LAYER_RECTS_JS)  # type: ignore[union-attr]
        _assert_layered_wrap_contract(rects)

    def test_explore_mode_letterboxes_without_cropping(
        self,
        page: "Page",
        composite_server_url: str,
        composite_slug: str,
    ) -> None:
        """Tap-to-zoom (explore) view: object-fit:contain — fully visible, no crop either axis."""
        page.set_viewport_size({"width": 500, "height": 900})  # type: ignore[union-attr]
        _goto_vn(page, composite_server_url, composite_slug, "vn-combo-a")

        page.click('button[aria-label="Focus image"]')  # type: ignore[union-attr]
        page.wait_for_selector(".vn-image-stage.explore", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        page.wait_for_function(  # type: ignore[union-attr]
            _IMAGES_LOADED_JS, arg=".vn-layer-bg, .vn-layer-fg", timeout=_PAGE_TIMEOUT_MS
        )

        styles = page.evaluate(  # type: ignore[union-attr]
            """() => {
                const cs = (el) => {
                    const s = getComputedStyle(el);
                    return { objectFit: s.objectFit, width: s.width, height: s.height };
                };
                return {
                    bg: cs(document.querySelector('.vn-layer-bg')),
                    fg: cs(document.querySelector('.vn-layer-fg')),
                };
            }"""
        )
        assert styles["bg"]["objectFit"] == "contain"
        assert styles["fg"]["objectFit"] == "contain"

        # object-fit:contain guarantees the whole image is visible within the element's own
        # box; confirm that box itself fills the stage (no additional cropping container).
        rects = page.evaluate(  # type: ignore[union-attr]
            """() => {
                const r = (el) => el.getBoundingClientRect();
                const stage = document.querySelector('.vn-image-stage');
                const bg = document.querySelector('.vn-layer-bg');
                const stageRect = r(stage);
                const bgRect = r(bg);
                return {
                    stageWidth: stageRect.width, stageHeight: stageRect.height,
                    bgWidth: bgRect.width, bgHeight: bgRect.height,
                };
            }"""
        )
        assert abs(rects["stageWidth"] - rects["bgWidth"]) < _TOL
        assert abs(rects["stageHeight"] - rects["bgHeight"]) < _TOL

        page.click('button[aria-label="Leave image exploration"]')  # type: ignore[union-attr]
        page.wait_for_selector(".vn-image-stage:not(.explore)", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]


class TestPlainPreviewComposite:
    """Non-VN reading mode: .lens-vn-composite / .lens-vn-bg / .lens-vn-fg (app.css)."""

    @pytest.mark.parametrize("node", ["vn-combo-a", "vn-combo-b"])
    @pytest.mark.parametrize("width", [360, 1400])
    def test_bg_defines_box_fg_matches_height_centered(
        self,
        page: "Page",
        composite_server_url: str,
        composite_slug: str,
        node: str,
        width: int,
    ) -> None:
        page.set_viewport_size({"width": width, "height": 800})  # type: ignore[union-attr]
        page.goto(f"{composite_server_url}#{composite_slug}/story/{node}")  # type: ignore[union-attr]
        page.wait_for_selector(".lens-vn-composite", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        page.wait_for_function(  # type: ignore[union-attr]
            _IMAGES_LOADED_JS, arg=".lens-vn-bg, .lens-vn-fg", timeout=_PAGE_TIMEOUT_MS
        )

        rects = page.evaluate(_PLAIN_RECTS_JS)  # type: ignore[union-attr]
        box, bg, fg = rects["box"], rects["bg"], rects["fg"]

        # bg defines the box: its own natural aspect, full container width, no forced crop.
        assert abs(bg["left"] - box["left"]) < _TOL
        assert abs(bg["right"] - box["right"]) < _TOL
        assert abs(bg["top"] - box["top"]) < _TOL
        assert abs(bg["height"] - box["height"]) < _TOL

        # fg matched to bg's rendered height, centered horizontally (side-crop/gap only).
        assert abs(fg["height"] - bg["height"]) < _TOL, (
            f"fg not in registration with bg: {fg} vs {bg}"
        )
        assert abs(fg["top"] - bg["top"]) < _TOL
        box_center = (box["left"] + box["right"]) / 2
        fg_center = (fg["left"] + fg["right"]) / 2
        assert abs(box_center - fg_center) < _TOL, f"fg not centered: {fg} vs box {box}"
