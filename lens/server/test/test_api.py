"""Server API integration tests.

These tests exercise the FastAPI routes against a real (temp) Lens project
populated by the session-scoped fixtures in conftest.py.  They use the
in-process TestClient for speed — no TCP sockets, no uvicorn.

Coverage intent:
- Every route returns the right shape at a high level.
- Project state (narrative, KB, node content) is correctly surfaced.
- Error paths (missing node, dataset mode) are handled.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestHealth:
    def test_ok(self, test_client: TestClient) -> None:
        r = test_client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestStats:
    def test_returns_200(self, test_client: TestClient) -> None:
        r = test_client.get("/stats")
        assert r.status_code == 200

    def test_active_narrative(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        assert data["active_narrative"] == "story"

    def test_kb_count_positive(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        # person.amy and place.forest were added during setup.
        assert data["kb_count"] >= 2

    def test_cursor_present(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        # After setup_test_project the cursor must be somewhere inside "story".
        assert data["cursor"] is not None
        assert "story" in data["cursor"]


class TestTree:
    def test_returns_list(self, test_client: TestClient) -> None:
        r = test_client.get("/tree")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_story_root_present(self, test_client: TestClient) -> None:
        data = test_client.get("/tree").json()
        addresses = [n["address"] for n in data]
        assert any("story" in a for a in addresses)


class TestNode:
    def test_root_node_by_narrative(self, test_client: TestClient) -> None:
        r = test_client.get("/node/story")
        assert r.status_code == 200
        data = r.json()
        assert "content" in data
        assert "address" in data

    def test_root_node_has_content(self, test_client: TestClient) -> None:
        data = test_client.get("/node/story").json()
        # setup_test_project ran the write operator → Lorem Ipsum should be there.
        assert "Lorem ipsum" in data["content"]

    def test_missing_node_returns_404(self, test_client: TestClient) -> None:
        r = test_client.get("/node/story/nonexistent-chapter")
        assert r.status_code == 404

    def test_children_is_list(self, test_client: TestClient) -> None:
        data = test_client.get("/node/story").json()
        assert isinstance(data["children"], list)
