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

    def test_projects_list(self, live_server_url: str, project_slug: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/projects") as resp:
            data = json.loads(resp.read())
        assert isinstance(data, list)
        slugs = [p["slug"] for p in data]
        assert project_slug in slugs

    def test_health(self, live_server_url: str, project_slug: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/health") as resp:
            data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert project_slug in data["projects"]

    def test_stats_has_narrative(self, live_server_url: str, project_slug: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/{project_slug}/stats") as resp:
            data = json.loads(resp.read())
        assert data["active_narrative"] == "story"
        assert data["kb_count"] >= 2
        assert "effective_pins_at_cursor" in data
        assert "remember_pins_at_cursor" in data
        assert "tts_available" in data
        assert data["tts_available"] is False

    def test_tree_returns_list(self, live_server_url: str, project_slug: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/{project_slug}/narrative/tree") as resp:
            data = json.loads(resp.read())
        assert isinstance(data, list)
        # /narrative/tree returns the children of the active narrative (not the root level);
        # each item must have address, key, and children fields if any items are present.
        for node in data:
            assert "address" in node
            assert "key" in node
            assert "children" in node

    def test_node_content(self, live_server_url: str, project_slug: str) -> None:
        with urllib.request.urlopen(f"{live_server_url}/{project_slug}/narrative/node/story") as resp:
            data = json.loads(resp.read())
        assert "Lorem ipsum" in data["content"]
