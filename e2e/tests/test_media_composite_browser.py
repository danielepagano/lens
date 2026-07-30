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

        cli = page.locator('[data-testid="cli-input"]')  # type: ignore[union-attr]
        cli.click()  # type: ignore[union-attr]
        cli.press_sequentially("/media-composite hero.png")  # type: ignore[union-attr]
        page.keyboard.press("Enter")  # type: ignore[union-attr]

        overlay = page.locator('[role="dialog"][aria-label="Chromakey preview"]')  # type: ignore[union-attr]
        overlay.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]

        # Preview loaded: image visible, resolved stats echoed (auto key = magenta).
        page.wait_for_selector(".carousel-spotlight img", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        resolved = page.locator(".composite-resolved")  # type: ignore[union-attr]
        resolved.wait_for(state="visible", timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        assert "#FF00FF" in resolved.inner_text()  # type: ignore[union-attr]

        # Tweak tolerance and re-preview.
        core_tol_input = overlay.locator("label", has_text="Core tol").locator("input")  # type: ignore[union-attr]
        core_tol_input.fill("30")  # type: ignore[union-attr]
        page.get_by_role("button", name="Preview").click()  # type: ignore[union-attr]
        page.wait_for_function(  # type: ignore[union-attr]
            "() => document.querySelector('.composite-resolved')?.textContent?.includes('core_tol 30.0')",
            timeout=_PAGE_TIMEOUT_MS,
        )

        # Save: button reflects saving -> saved, and the saved path is echoed.
        save_button = page.get_by_role("button", name="Save")  # type: ignore[union-attr]
        save_button.click()  # type: ignore[union-attr]
        page.wait_for_selector('button:has-text("Saved")', timeout=_PAGE_TIMEOUT_MS)  # type: ignore[union-attr]
        assert "hero_fg.png" in page.locator(".composite-saved-path").inner_text()  # type: ignore[union-attr]
