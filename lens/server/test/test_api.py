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

import json
from typing import Any

import pytest
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

    def test_narratives_list_included(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        assert "narratives" in data
        assert isinstance(data["narratives"], list)
        assert "story" in data["narratives"]

    def test_kb_count_positive(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        # person.amy and place.forest were added during setup.
        assert data["kb_count"] >= 2

    def test_cursor_present(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        # After setup_test_project the cursor must be somewhere inside "story".
        assert data["cursor"] is not None
        assert "story" in data["cursor"]

    def test_includes_transaction(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        assert "transaction" in data
        assert data["has_pending"] is False
        assert data["transaction"] is None

    def test_includes_effective_pins_at_cursor(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        assert "effective_pins_at_cursor" in data
        value = data["effective_pins_at_cursor"]
        assert isinstance(value, list)


class TestTree:
    def test_returns_list(self, test_client: TestClient) -> None:
        r = test_client.get("/narrative/tree")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_items_have_required_fields(self, test_client: TestClient) -> None:
        # Tree returns children of the active narrative, not all roots.
        # The test project's root node may have no children, so the list
        # may be empty — we just verify shape of any items that are present.
        data = test_client.get("/narrative/tree").json()
        for item in data:
            assert "address" in item
            assert "key" in item
            assert "children" in item


class TestNode:
    def test_root_node_by_narrative(self, test_client: TestClient) -> None:
        r = test_client.get("/narrative/node/story")
        assert r.status_code == 200
        data = r.json()
        assert "content" in data
        assert "address" in data

    def test_root_node_has_content(self, test_client: TestClient) -> None:
        data = test_client.get("/narrative/node/story").json()
        # setup_test_project ran the write operator → Lorem Ipsum should be there.
        assert "Lorem ipsum" in data["content"]

    def test_missing_node_returns_404(self, test_client: TestClient) -> None:
        r = test_client.get("/narrative/node/story/nonexistent-chapter")
        assert r.status_code == 404

    def test_children_is_list(self, test_client: TestClient) -> None:
        data = test_client.get("/narrative/node/story").json()
        assert isinstance(data["children"], list)


class TestNarratives:
    def test_set_active_and_verify_via_stats(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/narrative/narratives/active", json={"narrative": "api-test-narrative"}
        )
        assert r.status_code == 200
        assert r.json()["active"] == "api-test-narrative"
        assert test_client.get("/stats").json()["active_narrative"] == "api-test-narrative"

        r2 = test_client.post("/narrative/narratives/active", json={"narrative": "story"})
        assert r2.status_code == 200
        assert r2.json()["active"] == "story"
        assert test_client.get("/stats").json()["active_narrative"] == "story"

    def test_invalid_slug_returns_422(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/narrative/narratives/active", json={"narrative": "bad slug!"}
        )
        assert r.status_code == 422



def _consume_sse_stream(response: object) -> list[dict[str, Any]]:
    """Parse SSE events from a streaming response. Returns list of parsed data objects."""
    events: list[dict[str, Any]] = []
    assert hasattr(response, "iter_lines")
    buffer = ""
    for line in response.iter_lines():  # type: ignore[union-attr]
        if line:
            buffer += line + "\n"
        else:
            if buffer.startswith("data: "):
                payload: str = buffer[6:].strip()
                if payload:
                    events.append(json.loads(payload))
            buffer = ""
    return events


class TestCli:
    def test_run_stats_returns_stream_and_done(self, test_client: TestClient) -> None:
        r = test_client.post("/cli/run", json={"command": "stats"})
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        events = _consume_sse_stream(r)
        assert len(events) >= 1
        done = [e for e in events if e.get("type") == "done"]
        assert len(done) == 1
        assert done[0].get("exit_code") == 0

    def test_empty_command_shows_help(self, test_client: TestClient) -> None:
        r = test_client.post("/cli/run", json={"command": ""})
        assert r.status_code == 200
        events = _consume_sse_stream(r)
        done = [e for e in events if e.get("type") == "done"]
        assert len(done) == 1
        output = "".join(
            e.get("text", "") for e in events if e.get("type") in ("out", "err")
        )
        assert "Lens" in output or "usage" in output.lower() or "help" in output.lower()

    def test_cancel_when_no_run_returns_ok(self, test_client: TestClient) -> None:
        r = test_client.post("/cli/cancel")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    @pytest.mark.skip(
        reason="timing-dependent: first run often completes before second POST in CI"
    )
    def test_second_run_while_first_running_returns_409(
        self, test_client: TestClient
    ) -> None:
        import threading
        import time

        def run_first() -> None:
            r = test_client.post(
                "/cli/run", json={"command": "write continuing the story"}
            )
            if r.status_code == 200:
                for _ in r.iter_lines():
                    pass

        t = threading.Thread(target=run_first)
        t.start()
        time.sleep(0.05)
        r2 = test_client.post("/cli/run", json={"command": "stats"})
        t.join(timeout=15)
        if r2.status_code == 200:
            for _ in r2.iter_lines():
                pass
        assert r2.status_code == 409
