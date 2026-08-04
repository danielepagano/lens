"""Tests for the ``media_search`` command tool handler (command_tools.py).

Covers the handler's own argument/error handling, and — the point of
issue #114 — that it goes through ``MediaService.for_project`` and so shares
the one warm index with every other caller in the process rather than
building a throwaway cache per call.
"""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

from lens.core.command_tools import build_media_search_tool_entry
from lens.core.media import MediaService

_HANDLER = build_media_search_tool_entry()[1]


def _make_project_with_mount() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="lens_test_media_search_tool_"))
    (tmp / "lens.toml").write_text('[project]\nmount_point = "media"\n')
    (tmp / "media").mkdir()
    return tmp


def _call(args: dict[str, object], project_root: Path) -> str:
    async def _run() -> str:
        return await _HANDLER(args, project_root)

    return asyncio.run(_run())


class TestMediaSearchHandler:
    def setup_method(self) -> None:
        MediaService.clear_registry()

    def teardown_method(self) -> None:
        MediaService.clear_registry()

    def test_missing_query_is_an_error(self) -> None:
        root = _make_project_with_mount()
        assert _call({}, root) == "(error: query is required)"

    def test_blank_query_is_an_error(self) -> None:
        root = _make_project_with_mount()
        assert _call({"query": "   "}, root) == "(error: query is required)"

    def test_invalid_page_is_an_error(self) -> None:
        root = _make_project_with_mount()
        assert _call({"query": "amy", "page": "not-a-number"}, root) == (
            "(error: invalid page number: not-a-number)"
        )

    def test_no_mount_configured(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="lens_test_media_search_tool_"))
        (tmp / "lens.toml").write_text("[project]\n")
        out = _call({"query": "amy"}, tmp)
        assert "no media mount configured" in out

    def test_no_results_found(self) -> None:
        root = _make_project_with_mount()
        assert _call({"query": "amy"}, root) == "(no results found for query)"

    def test_finds_a_written_file(self) -> None:
        root = _make_project_with_mount()
        (root / "media" / "amy.jpg").write_bytes(b"hello")
        out = _call({"query": "amy"}, root)
        assert "amy.jpg" in out
        assert "1 of 1 total" in out

    def test_shares_the_warm_index_with_other_for_project_callers(self) -> None:
        # The regression issue #114 fixes: a write through a *different*
        # MediaService.for_project() handle (e.g. a server route, or a CLI
        # composite command) must be visible to this tool call without it
        # rebuilding its own cache. Warm this handler's view first so a
        # coincidental cold warm_cache() scan can't paper over independent
        # caches — see the equivalent guard in test_media_service.py.
        root = _make_project_with_mount()
        assert _call({"query": "amy"}, root) == "(no results found for query)"

        other = MediaService.for_project(root)
        assert other is not None
        other.put_file("", "amy.jpg", io.BytesIO(b"hello"))

        out = _call({"query": "amy"}, root)
        assert "amy.jpg" in out
