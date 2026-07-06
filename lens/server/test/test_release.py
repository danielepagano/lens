"""Server route tests for the release system.

Tests for ``POST /{slug}/release/request`` and release fields
in ``GET /{slug}/stats``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import tomllib
from fastapi.testclient import TestClient
class TestReleaseRequest:
    def test_request_valid(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/test/release/request",
            json={"target_version": "v99.0.0"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["requested_version"] == "99.0.0"
        assert len(data["requested_from_commit"]) > 0

    def test_request_invalid_tag(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/test/release/request",
            json={"target_version": "not-a-tag"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert "not a valid" in data["detail"]

    def test_request_missing_body_field(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/test/release/request",
            json={},
        )
        assert r.status_code == 422

    def test_request_writes_to_lens_toml(self, test_client: TestClient, test_project_dir: Path) -> None:
        r = test_client.post(
            "/test/release/request",
            json={"target_version": "v99.0.0"},
        )
        assert r.status_code == 200

        after = tomllib.loads((test_project_dir / "lens.toml").read_text())
        release = after.get("release", {})
        assert release.get("requested_version") == "99.0.0"
        assert len(release.get("requested_from_commit", "")) > 0

    def test_request_never_commits(
        self, test_client: TestClient, test_project_dir: Path
    ) -> None:
        before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=test_project_dir,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        r = test_client.post(
            "/test/release/request",
            json={"target_version": "v99.0.0"},
        )
        assert r.status_code == 200

        after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=test_project_dir,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        assert before == after, "request should not create a commit"


class TestReleaseClear:
    def test_clear_clears_fields(self, test_client: TestClient, test_project_dir: Path) -> None:
        # First make a request
        test_client.post(
            "/test/release/request",
            json={"target_version": "v99.0.0"},
        )

        r = test_client.post("/test/release/clear", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

        after = tomllib.loads((test_project_dir / "lens.toml").read_text())
        release = after.get("release", {})
        assert release.get("requested_version") == ""
        assert release.get("requested_from_commit") == ""

    def test_clear_never_commits(self, test_client: TestClient, test_project_dir: Path) -> None:
        test_client.post(
            "/test/release/request",
            json={"target_version": "v99.0.0"},
        )

        before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=test_project_dir,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        r = test_client.post("/test/release/clear", json={})
        assert r.status_code == 200

        after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=test_project_dir,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        assert before == after, "clear should not create a commit"

    def test_clear_when_nothing_requested_is_noop(
        self, test_client: TestClient
    ) -> None:
        r = test_client.post("/test/release/clear", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
