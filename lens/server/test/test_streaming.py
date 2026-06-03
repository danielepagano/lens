"""Unit tests for SSE streaming helpers (disconnect watcher, lock)."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from lens.core.project import ProjectSession
from lens.server.streaming import StreamLock, watch_client_disconnect


def _init_repo(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )


class TestWatchClientDisconnect(unittest.IsolatedAsyncioTestCase):
    async def test_sets_cancel_event_when_client_disconnects(self) -> None:
        lock = StreamLock()
        lock.acquire("write")
        request = MagicMock()
        request.is_disconnected = AsyncMock(side_effect=[False, False, True])

        await watch_client_disconnect(request, lock, session=None)

        self.assertTrue(lock.cancel_event.is_set())

    async def test_abort_stream_on_disconnect_with_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _init_repo(root)
            (root / "lens.toml").write_text('[project]\nnarrative = "n"\n')
            nd = root / "narrative" / "n"
            nd.mkdir(parents=True)
            (nd / "_node.md").write_text("# n\n")
            (root / "knowledge").mkdir()
            subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "project"],
                cwd=root,
                capture_output=True,
                check=True,
            )
            session = ProjectSession(root, root)
            lock = StreamLock()
            lock.acquire("write")

            request = MagicMock()
            request.is_disconnected = AsyncMock(return_value=True)

            await watch_client_disconnect(request, lock, session=session)

            self.assertTrue(lock.cancel_event.is_set())

    async def test_exits_when_cancelled_before_disconnect(self) -> None:
        lock = StreamLock()
        lock.acquire("write")
        lock.cancel_event.set()
        request = MagicMock()
        request.is_disconnected = AsyncMock(return_value=False)

        await asyncio.wait_for(
            watch_client_disconnect(request, lock, session=None),
            timeout=1.0,
        )

        request.is_disconnected.assert_not_called()
