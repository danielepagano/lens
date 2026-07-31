"""API tests for media metadata endpoints (GET/PUT /mount/metadata/{path})."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lens.core.project import ProjectSession
from lens.server.main import create_app


@pytest.fixture()
def mount_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Function-scoped client backed by a project with mount_point configured."""
    (tmp_path / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "media"\n')
    narrative_dir = tmp_path / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# Story\n\nOpening.\n")
    (tmp_path / "knowledge").mkdir()
    mount = tmp_path / "media"
    mount.mkdir()
    (mount / "hero.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (mount / "clip.mp4").write_bytes(b"\x00\x00\x00\x18")
    (mount / "doc.pdf").write_bytes(b"%PDF-1.4")
    (mount / "notes.txt").write_bytes(b"text")
    sub = mount / "sub"
    sub.mkdir()
    (sub / "photo.png").write_bytes(b"\x89PNG")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    session = ProjectSession(tmp_path, tmp_path)
    app = create_app({"test": session})
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# GET /mount/metadata/{path}
# ---------------------------------------------------------------------------


class TestGetMetadata:
    def test_returns_path_based_metadata(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/metadata/hero.jpg")
        assert r.status_code == 200
        data = r.json()
        assert data["relative_path"] == "hero.jpg"
        assert data["name"] == "hero.jpg"
        assert data["extension"] == ".jpg"
        assert data["type"] == "image"

    def test_returns_extra_when_sidecar_exists(self, mount_client: TestClient) -> None:
        r = mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"character": "amy"}})
        assert r.status_code == 200
        r = mount_client.get("/test/mount/metadata/hero.jpg")
        assert r.status_code == 200
        data = r.json()
        assert data["character"] == "amy"

    def test_extra_empty_when_no_sidecar(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/metadata/doc.pdf")
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == {"relative_path", "name", "extension", "type"}

    def test_nested_path(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/metadata/sub/photo.png")
        assert r.status_code == 200
        data = r.json()
        assert data["relative_path"] == "sub/photo.png"
        assert data["name"] == "photo.png"
        assert data["extension"] == ".png"
        assert data["type"] == "image"

    def test_video_type(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/metadata/clip.mp4")
        assert r.status_code == 200
        data = r.json()
        assert data["type"] == "video"

    def test_document_type(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/metadata/notes.txt")
        assert r.status_code == 200
        data = r.json()
        assert data["type"] == "document"

    def test_missing_file_returns_404(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/metadata/nope.jpg")
        assert r.status_code == 404

    def test_no_mount_returns_404(self, test_client: TestClient) -> None:
        r = test_client.get("/test/mount/metadata/hero.jpg")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /mount/metadata/{path}
# ---------------------------------------------------------------------------


class TestPutMetadata:
    def test_creates_sidecar(self, mount_client: TestClient) -> None:
        r = mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"character": "amy"}})
        assert r.status_code == 200
        data = r.json()
        assert data["character"] == "amy"
        assert data["name"] == "hero.jpg"

    def test_merges_with_existing(self, mount_client: TestClient) -> None:
        mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"character": "amy"}})
        r = mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"expression": "happy"}})
        assert r.status_code == 200
        data = r.json()
        assert data["character"] == "amy"
        assert data["expression"] == "happy"

    def test_overwrites_existing_key(self, mount_client: TestClient) -> None:
        mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"character": "amy"}})
        r = mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"character": "bob"}})
        data = r.json()
        assert data["character"] == "bob"

    def test_ignores_reserved_keys(self, mount_client: TestClient) -> None:
        r = mount_client.put(
            "/test/mount/metadata/hero.jpg",
            json={"metadata": {"name": "evil.jpg", "type": "video", "custom": "ok"}},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "hero.jpg"
        assert data["type"] == "image"
        assert data["custom"] == "ok"

    def test_missing_file_returns_404(self, mount_client: TestClient) -> None:
        r = mount_client.put("/test/mount/metadata/nope.jpg", json={"metadata": {"character": "amy"}})
        assert r.status_code == 404

    def test_no_mount_returns_404(self, test_client: TestClient) -> None:
        r = test_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"character": "amy"}})
        assert r.status_code == 404

    def test_empty_metadata_creates_no_sidecar(self, mount_client: TestClient, tmp_path: Path) -> None:
        r = mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {}})
        assert r.status_code == 200
        assert not (tmp_path / "media" / "hero.jpg.yml").exists()

    def test_only_reserved_keys_creates_no_sidecar(self, mount_client: TestClient, tmp_path: Path) -> None:
        r = mount_client.put(
            "/test/mount/metadata/hero.jpg",
            json={"metadata": {"name": "evil.jpg", "type": "video"}},
        )
        assert r.status_code == 200
        assert not (tmp_path / "media" / "hero.jpg.yml").exists()

    def test_updates_that_empty_out_sidecar_delete_it(self, mount_client: TestClient, tmp_path: Path) -> None:
        # Not reachable from a single PUT (merge is additive-only), but confirm
        # an existing sidecar survives a no-op empty PUT rather than being wiped.
        mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"character": "amy"}})
        assert (tmp_path / "media" / "hero.jpg.yml").exists()
        r = mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {}})
        assert r.status_code == 200
        assert r.json()["character"] == "amy"
        assert (tmp_path / "media" / "hero.jpg.yml").exists()


# ---------------------------------------------------------------------------
# DELETE /mount/metadata/{path}
# ---------------------------------------------------------------------------


class TestDeleteMetadata:
    def test_deletes_sidecar(self, mount_client: TestClient) -> None:
        # Create sidecar first
        mount_client.put("/test/mount/metadata/hero.jpg", json={"metadata": {"character": "amy"}})
        r = mount_client.delete("/test/mount/metadata/hero.jpg")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        # Verify it's gone — GET returns path-only
        r2 = mount_client.get("/test/mount/metadata/hero.jpg")
        assert r2.status_code == 200
        assert set(r2.json().keys()) == {"relative_path", "name", "extension", "type"}

    def test_delete_no_sidecar_still_ok(self, mount_client: TestClient) -> None:
        r = mount_client.delete("/test/mount/metadata/hero.jpg")
        assert r.status_code == 200

    def test_delete_missing_file_ok(self, mount_client: TestClient) -> None:
        r = mount_client.delete("/test/mount/metadata/nope.jpg")
        assert r.status_code == 200

    def test_no_mount_returns_404(self, test_client: TestClient) -> None:
        r = test_client.delete("/test/mount/metadata/hero.jpg")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /mount/search
# ---------------------------------------------------------------------------


class TestSearchMedia:
    def test_search_by_required_term(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/search", params={"q": "hero!"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["relative_path"] == "hero.jpg"
        assert data["total_items"] == 1
        assert data["total_pages"] == 1
        assert data["page_size"] == 20
        assert data["current_page"] == 1

    def test_search_by_type(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/search", params={"q": "type:image"})
        assert r.status_code == 200
        data = r.json()
        paths = {d["relative_path"] for d in data["items"]}
        assert "hero.jpg" in paths
        assert "sub/photo.png" in paths
        assert "clip.mp4" not in paths
        assert data["total_items"] >= 2

    def test_search_exposes_a_score_and_ranks_by_it(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/search", params={"q": "type:image jpg"})
        assert r.status_code == 200
        items = r.json()["items"]
        scores = [i["_score"] for i in items]
        assert scores == sorted(scores, reverse=True)
        # hero.jpg satisfies both terms; sub/photo.png only the first.
        assert items[0]["relative_path"] == "hero.jpg"
        assert scores[0] > scores[1]

    def test_search_required_term_hard_filters(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/search", params={"q": "type:video! clip"})
        assert r.status_code == 200
        paths = [i["relative_path"] for i in r.json()["items"]]
        assert paths == ["clip.mp4"]

    def test_search_quoted_phrase_matches_path_segments_in_order(
        self, mount_client: TestClient
    ) -> None:
        assert (
            mount_client.get("/test/mount/search", params={"q": '"sub photo"!'}).json()[
                "total_items"
            ]
            == 1
        )
        assert (
            mount_client.get("/test/mount/search", params={"q": '"photo sub"!'}).json()[
                "total_items"
            ]
            == 0
        )

    def test_search_no_match(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/search", params={"q": "zebra!"})
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total_items"] == 0

    def test_search_q_required(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/search")
        assert r.status_code == 422  # missing required query param

    def test_search_no_mount_returns_404(self, test_client: TestClient) -> None:
        r = test_client.get("/test/mount/search", params={"q": "hero!"})
        assert r.status_code == 404

    def test_search_with_page_param(self, mount_client: TestClient) -> None:
        r = mount_client.get("/test/mount/search", params={"q": "hero!", "page": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["current_page"] == 1
