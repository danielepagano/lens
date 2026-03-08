"""API smoke tests for the Lens server — no browser required.

These tests verify the server is reachable and returning the right shapes
from a real (temp) Lens project with a running fake LLM.

Running::

    poe test-e2e

    # or against a running dev server:
    LENS_DEV_SERVER_URL=http://127.0.0.1:8000 pytest e2e/

Browser tests live in ``test_browser.py`` (requires ``playwright install chromium``).
"""

from __future__ import annotations

import json
import urllib.request


class TestApiSmoke:
    """Verify that core API routes respond correctly against the test project."""

    def test_health(self, live_server_url: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/health") as resp:
            data = json.loads(resp.read())
        assert data == {"status": "ok"}

    def test_stats_has_narrative(self, live_server_url: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/stats") as resp:
            data = json.loads(resp.read())
        assert data["active_narrative"] == "story"
        assert data["kb_count"] >= 2

    def test_tree_has_story(self, live_server_url: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/tree") as resp:
            data = json.loads(resp.read())
        assert isinstance(data, list)
        assert any("story" in n.get("address", "") for n in data)

    def test_node_content(self, live_server_url: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/node/story") as resp:
            data = json.loads(resp.read())
        assert "Lorem ipsum" in data["content"]
