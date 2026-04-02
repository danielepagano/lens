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

import subprocess
from collections.abc import Generator
from pathlib import Path

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


# ---------------------------------------------------------------------------
# TestAttach — /mount/browse, /mount/file, POST /attach
# ---------------------------------------------------------------------------


def _init_repo_for_attach(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp, capture_output=True, check=True)
    (tmp / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)


@pytest.fixture()
def attach_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Function-scoped client backed by a project with a mount_point configured."""
    from lens.core.project import ProjectSession
    from lens.server.main import create_app

    # Minimal Lens project with mount_point = "media"
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
    (mount / ".hidden").write_bytes(b"hidden")      # should be filtered out
    (mount / "script.sh").write_bytes(b"#!/bin/sh")  # unsupported, filtered out
    sub = mount / "sub"
    sub.mkdir()
    (sub / "photo.png").write_bytes(b"\x89PNG")
    _init_repo_for_attach(tmp_path)

    session = ProjectSession(tmp_path, tmp_path)
    app = create_app(session)
    with TestClient(app) as client:
        yield client


class TestMountBrowse:
    def test_no_mount_returns_empty(self, test_client: TestClient) -> None:
        # The shared test project has no mount_point
        r = test_client.get("/mount/browse")
        assert r.status_code == 200
        assert r.json() == []

    def test_root_lists_entries(self, attach_client: TestClient) -> None:
        r = attach_client.get("/mount/browse")
        assert r.status_code == 200
        data = r.json()
        names = [e["name"] for e in data]
        assert "hero.jpg" in names
        assert "sub" in names

    def test_entries_have_is_dir_flag(self, attach_client: TestClient) -> None:
        data = attach_client.get("/mount/browse").json()
        dirs = [e for e in data if e["is_dir"]]
        files = [e for e in data if not e["is_dir"]]
        assert any(d["name"] == "sub" for d in dirs)
        assert any(f["name"] == "hero.jpg" for f in files)

    def test_hidden_files_excluded(self, attach_client: TestClient) -> None:
        data = attach_client.get("/mount/browse").json()
        names = [e["name"] for e in data]
        assert ".hidden" not in names

    def test_unsupported_extension_files_excluded(self, attach_client: TestClient) -> None:
        data = attach_client.get("/mount/browse").json()
        names = [e["name"] for e in data]
        assert "script.sh" not in names

    def test_txt_file_included(self, attach_client: TestClient) -> None:
        data = attach_client.get("/mount/browse").json()
        names = [e["name"] for e in data]
        assert "notes.txt" in names

    def test_subdirectory_listing(self, attach_client: TestClient) -> None:
        r = attach_client.get("/mount/browse?path=sub")
        assert r.status_code == 200
        data = r.json()
        assert any(e["name"] == "photo.png" for e in data)

    def test_dirs_sorted_before_files(self, attach_client: TestClient) -> None:
        data = attach_client.get("/mount/browse").json()
        # All dirs should appear before all files
        kinds = ["dir" if e["is_dir"] else "file" for e in data]
        dir_indices = [i for i, k in enumerate(kinds) if k == "dir"]
        file_indices = [i for i, k in enumerate(kinds) if k == "file"]
        if dir_indices and file_indices:
            assert max(dir_indices) < min(file_indices)


class TestMountProxyFile:
    def test_no_mount_returns_404(self, test_client: TestClient) -> None:
        r = test_client.get("/mount/file/hero.jpg")
        assert r.status_code == 404

    def test_existing_file_returns_200(self, attach_client: TestClient) -> None:
        r = attach_client.get("/mount/file/hero.jpg")
        assert r.status_code == 200

    def test_missing_file_returns_404(self, attach_client: TestClient) -> None:
        r = attach_client.get("/mount/file/nonexistent.jpg")
        assert r.status_code == 404

    def test_path_traversal_blocked(self, attach_client: TestClient) -> None:
        # ASGI normalizes `..` segments in URLs before routing, so the path
        # `/mount/file/../../etc/passwd` becomes `/etc/passwd` and returns 404
        # (no route match).  Either 400 or 404 confirms the traversal is blocked.
        r = attach_client.get("/mount/file/../../etc/passwd")
        assert r.status_code in (400, 404)

    def test_file_in_subdir(self, attach_client: TestClient) -> None:
        r = attach_client.get("/mount/file/sub/photo.png")
        assert r.status_code == 200


class TestAttachEndpoint:
    def test_no_mount_returns_error(self, test_client: TestClient) -> None:
        r = test_client.post("/attach", json={"path": "hero.jpg"})
        assert r.status_code == 200
        assert r.json()["status"] == "error"
        assert "mount_point" in r.json()["detail"]

    def test_valid_image_returns_ok(self, attach_client: TestClient) -> None:
        r = attach_client.post("/attach", json={"path": "hero.jpg"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["type"] == "image"
        assert "hero.jpg" in data["embed"]

    def test_video_attach_returns_ok(self, attach_client: TestClient) -> None:
        r = attach_client.post("/attach", json={"path": "clip.mp4"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["type"] == "video"

    def test_unsupported_extension_returns_error(self, attach_client: TestClient) -> None:
        r = attach_client.post("/attach", json={"path": "file.xyz"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert "unsupported" in data["detail"]

    def test_missing_file_returns_error(self, attach_client: TestClient) -> None:
        r = attach_client.post("/attach", json={"path": "ghost.png"})
        assert r.status_code == 200
        assert r.json()["status"] == "error"

    def test_attach_with_address_and_line_returns_ok(self, attach_client: TestClient) -> None:
        r = attach_client.post(
            "/attach",
            json={"path": "hero.jpg", "address": "/", "line": 1},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "hero.jpg" in data["embed"]

    def test_attach_invalid_line_returns_error(self, attach_client: TestClient) -> None:
        r = attach_client.post(
            "/attach",
            json={"path": "hero.jpg", "address": "/", "line": 999},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "error"
        assert "out of range" in r.json()["detail"]


class TestStatsHasMount:
    def test_has_mount_false_without_config(self, test_client: TestClient) -> None:
        data = test_client.get("/stats").json()
        assert data["has_mount"] is False

    def test_has_mount_true_with_config(self, attach_client: TestClient) -> None:
        data = attach_client.get("/stats").json()
        assert data["has_mount"] is True
