"""Tests for ``GET /{slug}/explain``."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestExplainRoute:
    def test_returns_a_report_for_the_cursor(self, test_client: TestClient) -> None:
        r = test_client.get("/test/explain")
        assert r.status_code == 200
        data = r.json()
        assert data["operator"]
        assert data["blocks"]
        assert data["totals"]["bytes"] > 0

    def test_totals_add_up(self, test_client: TestClient) -> None:
        totals = test_client.get("/test/explain").json()["totals"]
        assert totals["bytes"] == totals["accounted_bytes"] + totals["other_bytes"]

    def test_blocks_carry_components_with_provenance(
        self, test_client: TestClient
    ) -> None:
        blocks = test_client.get("/test/explain").json()["blocks"]
        knowledge = next(b for b in blocks if b["id"] == "relevant_knowledge")
        amy = next(c for c in knowledge["components"] if c["id"] == "kb:person.amy")
        assert amy["provenance_kind"] == "node_pin"
        assert amy["bytes"] > 0

    def test_operator_query_selects_the_operator(self, test_client: TestClient) -> None:
        data = test_client.get("/test/explain", params={"operator": "section"}).json()
        assert data["operator"] == "section"

    def test_unknown_operator_is_a_400(self, test_client: TestClient) -> None:
        r = test_client.get("/test/explain", params={"operator": "nope"})
        assert r.status_code == 400
        assert "unknown operator" in r.json()["detail"]

    def test_missing_node_is_a_400(self, test_client: TestClient) -> None:
        r = test_client.get("/test/explain", params={"address": "/no-such-node"})
        assert r.status_code == 400

    def test_invalid_sort_is_rejected_by_validation(
        self, test_client: TestClient
    ) -> None:
        r = test_client.get("/test/explain", params={"sort": "sideways"})
        assert r.status_code == 422

    def test_sort_size_is_accepted(self, test_client: TestClient) -> None:
        blocks = test_client.get("/test/explain", params={"sort": "size"}).json()[
            "blocks"
        ]
        for block in blocks:
            sizes = [c["bytes"] for c in block["components"]]
            assert sizes == sorted(sizes, reverse=True)

    def test_unknown_project_is_a_404(self, test_client: TestClient) -> None:
        assert test_client.get("/nope/explain").status_code == 404
