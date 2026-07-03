"""Server route tests for the release system (Phase 5).

Uses function-scoped fixtures (not the session-scoped test client) so each
test group sets up exactly the ``lens.toml`` configuration it needs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient


def _init_git(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp, capture_output=True, check=True)
    # Needed so `git commit` can create a HEAD.
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)


RELEASE_TOML = """\
[project]
narrative = "story"

[release]
enabled = true
auto_update = "minor"
"""

NO_RELEASE_TOML = """\
[project]
narrative = "story"
"""


def _build_client(tmp: Path, toml: str) -> TestClient:
    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    _init_git(tmp)
    (tmp / "lens.toml").write_text(toml)
    narrative_dir = tmp / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# Story\n\nOpening.\n")
    (tmp / "knowledge").mkdir()

    session = ProjectSession(tmp, tmp)
    app = create_app({"test": session})
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def release_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    yield _build_client(tmp_path, RELEASE_TOML)


@pytest.fixture()
def no_release_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    yield _build_client(tmp_path, NO_RELEASE_TOML)


# ---------------------------------------------------------------------------
# GET /release/status
# ---------------------------------------------------------------------------


class TestReleaseStatus:
    def test_returns_200_when_enabled(self, release_client: TestClient) -> None:
        r = release_client.get("/test/release/status")
        assert r.status_code == 200

    def test_returns_expected_fields(self, release_client: TestClient) -> None:
        data = release_client.get("/test/release/status").json()
        assert data["enabled"] is True
        assert data["auto_update"] == "minor"
        assert data["requested_version"] == ""
        assert data["gated_update_pending"] is False
        assert data["gated_update_target_version"] == ""
        assert data["gated_update_approved"] is False
        assert data["app_leader"] is False
        assert data["installed_version"] is None
        assert data["latest_available"] is None

    def test_returns_404_when_not_enabled(self, no_release_client: TestClient) -> None:
        r = no_release_client.get("/test/release/status")
        assert r.status_code == 404
        assert "not enabled" in r.json()["detail"]


# ---------------------------------------------------------------------------
# POST /release/policy
# ---------------------------------------------------------------------------


class TestReleasePolicy:
    def test_updates_auto_update(self, release_client: TestClient) -> None:
        r = release_client.post("/test/release/policy", json={"auto_update": "major"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        data = release_client.get("/test/release/status").json()
        assert data["auto_update"] == "major"

    def test_updates_requested_version(self, release_client: TestClient) -> None:
        r = release_client.post(
            "/test/release/policy", json={"requested_version": "v2.0.0"}
        )
        assert r.status_code == 200

        data = release_client.get("/test/release/status").json()
        assert data["requested_version"] == "v2.0.0"

    def test_invalid_auto_update_returns_error(self, release_client: TestClient) -> None:
        r = release_client.post(
            "/test/release/policy", json={"auto_update": "invalid"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "error"

    def test_noop_sends_no_body_is_ok(self, release_client: TestClient) -> None:
        r = release_client.post("/test/release/policy", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_returns_404_when_not_enabled(self, no_release_client: TestClient) -> None:
        r = no_release_client.post(
            "/test/release/policy", json={"auto_update": "minor"}
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /release/gated-update/approve
# ---------------------------------------------------------------------------


class TestReleaseGatedApprove:
    def test_approve_returns_ok(self, release_client: TestClient) -> None:
        r = release_client.post("/test/release/gated-update/approve")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_approve_sets_flag(self, release_client: TestClient) -> None:
        release_client.post("/test/release/gated-update/approve")
        data = release_client.get("/test/release/status").json()
        assert data["gated_update_approved"] is True

    def test_returns_404_when_not_enabled(self, no_release_client: TestClient) -> None:
        r = no_release_client.post("/test/release/gated-update/approve")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /release/gated-update/reject
# ---------------------------------------------------------------------------


class TestReleaseGatedReject:
    def test_reject_returns_ok(self, release_client: TestClient) -> None:
        r = release_client.post("/test/release/gated-update/reject")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_reject_clears_flags(self, release_client: TestClient) -> None:
        # First approve, then reject, then verify cleared.
        release_client.post("/test/release/gated-update/approve")
        release_client.post("/test/release/gated-update/reject")
        data = release_client.get("/test/release/status").json()
        assert data["gated_update_pending"] is False
        assert data["gated_update_target_version"] == ""
        assert data["gated_update_approved"] is False

    def test_returns_404_when_not_enabled(self, no_release_client: TestClient) -> None:
        r = no_release_client.post("/test/release/gated-update/reject")
        assert r.status_code == 404
