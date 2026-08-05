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

from lens.testing.fake_llm import FakeLLMServer
from lens.testing.project import setup_test_project


class TestHealth:
    def test_ok(self, test_client: TestClient) -> None:
        r = test_client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "test" in data["projects"]


class TestStats:
    def test_returns_200(self, test_client: TestClient) -> None:
        r = test_client.get("/test/stats")
        assert r.status_code == 200

    def test_active_narrative(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert data["active_narrative"] == "story"

    def test_narratives_list_included(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert "narratives" in data
        assert isinstance(data["narratives"], list)
        assert "story" in data["narratives"]

    def test_kb_count_positive(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        # person.amy and place.forest were added during setup.
        assert data["kb_count"] >= 2

    def test_cursor_present(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        # After setup_test_project the cursor must be somewhere inside "story".
        assert data["cursor"] is not None
        assert "story" in data["cursor"]

    def test_includes_transaction(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert "transaction" in data
        assert data["has_pending"] is False
        assert data["transaction"] is None

    def test_includes_effective_pins_at_cursor(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert "effective_pins_at_cursor" in data
        value = data["effective_pins_at_cursor"]
        assert isinstance(value, list)

    def test_includes_remember_pins_at_cursor(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert "remember_pins_at_cursor" in data
        assert isinstance(data["remember_pins_at_cursor"], dict)

    def test_includes_effective_vars_and_params_at_cursor(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert "effective_vars_at_cursor" in data
        assert isinstance(data["effective_vars_at_cursor"], dict)
        assert "effective_params_at_cursor" in data
        assert isinstance(data["effective_params_at_cursor"], dict)
        for k, v in data["effective_params_at_cursor"].items():
            assert isinstance(k, str)
            assert isinstance(v, str)

    def test_includes_image_backends_shape(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert isinstance(data["image_backends"], list)
        for row in data["image_backends"]:
            assert isinstance(row, dict)
            assert "id" in row
            assert isinstance(row["aspect_ratios"], list)
            assert isinstance(row["sizes"], list)
            assert row["default_batch"] == 1
            assert isinstance(row["max_batch"], int)
            assert "supports_reference_images" in row
            assert isinstance(row["supports_reference_images"], bool)

    def test_includes_cloud_mount(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert "cloud_mount" in data
        assert data["cloud_mount"] is False

    def test_includes_reference_images_supported(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert "reference_images_supported" in data
        assert isinstance(data["reference_images_supported"], bool)

    def test_includes_tts_available(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert "tts_available" in data
        assert data["tts_available"] is False

    def test_includes_modalities_fields(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert isinstance(data["registered_modality_ids"], list)
        assert isinstance(data["modalities_at_cursor"], dict)

    def test_modalities_at_cursor_reflects_pin_writes(
        self, test_client: TestClient
    ) -> None:
        r = test_client.post(
            "/test/narrative/pin",
            json={
                "kind": "modality",
                "operation": "set",
                "modality_id": "media_attach",
                "key": "anchor",
                "value": "amy!",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        data = test_client.get("/test/stats").json()
        entry = data["modalities_at_cursor"]["media_attach"]
        assert entry["config"] == {"anchor": "amy!"}
        # This client's project has no mount_point configured, so the gate
        # still fails -- config presence and gate outcome are independent.
        assert entry["active"] is False
        assert entry["reason"] == "no mount_point configured in lens.toml"

        r = test_client.post(
            "/test/narrative/pin",
            json={
                "kind": "modality",
                "operation": "unset",
                "modality_id": "media_attach",
                "key": "anchor",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        data = test_client.get("/test/stats").json()
        assert "media_attach" not in data["modalities_at_cursor"]

    def test_modality_pin_requires_modality_id(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/test/narrative/pin",
            json={"kind": "modality", "operation": "set", "key": "enabled", "value": True},
        )
        assert r.status_code == 422


class TestTree:
    def test_returns_list(self, test_client: TestClient) -> None:
        r = test_client.get("/test/narrative/tree")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_items_have_required_fields(self, test_client: TestClient) -> None:
        # Tree returns children of the active narrative, not all roots.
        # The test project's root node may have no children, so the list
        # may be empty — we just verify shape of any items that are present.
        data = test_client.get("/test/narrative/tree").json()
        for item in data:
            assert "address" in item
            assert "key" in item
            assert "children" in item


class TestNode:
    def test_root_node_by_narrative(self, test_client: TestClient) -> None:
        r = test_client.get("/test/narrative/node/story")
        assert r.status_code == 200
        data = r.json()
        assert "content" in data
        assert "address" in data

    def test_root_node_has_content(self, test_client: TestClient) -> None:
        data = test_client.get("/test/narrative/node/story").json()
        # setup_test_project ran the write operator → Lorem Ipsum should be there.
        assert "Lorem ipsum" in data["content"]

    def test_missing_node_returns_404(self, test_client: TestClient) -> None:
        r = test_client.get("/test/narrative/node/story/nonexistent-chapter")
        assert r.status_code == 404

    def test_children_is_list(self, test_client: TestClient) -> None:
        data = test_client.get("/test/narrative/node/story").json()
        assert isinstance(data["children"], list)


class TestNarratives:
    def test_set_active_and_verify_via_stats(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/test/narrative/narratives/active", json={"narrative": "api-test-narrative"}
        )
        assert r.status_code == 200
        assert r.json()["active"] == "api-test-narrative"
        assert test_client.get("/test/stats").json()["active_narrative"] == "api-test-narrative"

        r2 = test_client.post("/test/narrative/narratives/active", json={"narrative": "story"})
        assert r2.status_code == 200
        assert r2.json()["active"] == "story"
        assert test_client.get("/test/stats").json()["active_narrative"] == "story"

    def test_invalid_slug_returns_422(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/test/narrative/narratives/active", json={"narrative": "bad slug!"}
        )
        assert r.status_code == 422


class TestCompanionNarrativeCreate:
    def test_companion_chat_creates_root_and_kb_stubs(
        self, fake_llm: FakeLLMServer, tmp_path: Path
    ) -> None:
        from lens.core.project import ProjectSession
        from lens.server.main import create_app

        setup_test_project(tmp_path, fake_llm.base_url, datasets=["testing", "companion"])
        session = ProjectSession(tmp_path, tmp_path)
        app = create_app({"test": session})
        with TestClient(app) as client:
            r = client.post(
                "/test/narrative/narratives/active",
                json={
                    "narrative": "social",
                    "narrative_kind": "companion_chat",
                    "companion_as_kb_id": "companion.mara",
                    "companion_with_kb_id": "human.adam",
                },
            )
            assert r.status_code == 200
            data = r.json()
            assert data["active"] == "social"
            assert "companion_bootstrap" in data
            root = tmp_path / "narrative" / "social" / "_node.md"
            text = root.read_text(encoding="utf-8")
            assert "kb_pin:" in text
            assert "companion.mara+" in text
            assert "human.adam+" in text
            assert "meta.companion" not in text
            assert "companion.mara" in text
            assert "human.adam" in text
            assert "# Mara & Adam" in text
            assert (tmp_path / "knowledge" / "companion" / "mara.md").is_file()

    def test_companion_chat_requires_companion_dataset(self, test_client: TestClient) -> None:
        r = test_client.post(
            "/test/narrative/narratives/active",
            json={
                "narrative": "solo",
                "narrative_kind": "companion_chat",
                "companion_as_kb_id": "companion.a",
                "companion_with_kb_id": "human.b",
            },
        )
        assert r.status_code == 400


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
    app = create_app({"test": session})
    with TestClient(app) as client:
        yield client


class TestMountBrowse:
    def test_no_mount_returns_empty(self, test_client: TestClient) -> None:
        # The shared test project has no mount_point
        r = test_client.get("/test/mount/browse")
        assert r.status_code == 200
        assert r.json() == []

    def test_root_lists_entries(self, attach_client: TestClient) -> None:
        r = attach_client.get("/test/mount/browse")
        assert r.status_code == 200
        data = r.json()
        names = [e["name"] for e in data]
        assert "hero.jpg" in names
        assert "sub" in names

    def test_entries_have_is_dir_flag(self, attach_client: TestClient) -> None:
        data = attach_client.get("/test/mount/browse").json()
        dirs = [e for e in data if e["is_dir"]]
        files = [e for e in data if not e["is_dir"]]
        assert any(d["name"] == "sub" for d in dirs)
        assert any(f["name"] == "hero.jpg" for f in files)

    def test_hidden_files_excluded(self, attach_client: TestClient) -> None:
        data = attach_client.get("/test/mount/browse").json()
        names = [e["name"] for e in data]
        assert ".hidden" not in names

    def test_unsupported_extension_files_excluded(self, attach_client: TestClient) -> None:
        data = attach_client.get("/test/mount/browse").json()
        names = [e["name"] for e in data]
        assert "script.sh" not in names

    def test_txt_file_included(self, attach_client: TestClient) -> None:
        data = attach_client.get("/test/mount/browse").json()
        names = [e["name"] for e in data]
        assert "notes.txt" in names

    def test_subdirectory_listing(self, attach_client: TestClient) -> None:
        r = attach_client.get("/test/mount/browse?path=sub")
        assert r.status_code == 200
        data = r.json()
        assert any(e["name"] == "photo.png" for e in data)

    def test_dirs_sorted_before_files(self, attach_client: TestClient) -> None:
        data = attach_client.get("/test/mount/browse").json()
        # All dirs should appear before all files
        kinds = ["dir" if e["is_dir"] else "file" for e in data]
        dir_indices = [i for i, k in enumerate(kinds) if k == "dir"]
        file_indices = [i for i, k in enumerate(kinds) if k == "file"]
        if dir_indices and file_indices:
            assert max(dir_indices) < min(file_indices)


class TestMountProxyFile:
    def test_no_mount_returns_404(self, test_client: TestClient) -> None:
        r = test_client.get("/test/mount/file/hero.jpg")
        assert r.status_code == 404

    def test_existing_file_returns_200(self, attach_client: TestClient) -> None:
        r = attach_client.get("/test/mount/file/hero.jpg")
        assert r.status_code == 200

    def test_missing_file_returns_404(self, attach_client: TestClient) -> None:
        r = attach_client.get("/test/mount/file/nonexistent.jpg")
        assert r.status_code == 404

    def test_path_traversal_blocked(self, attach_client: TestClient) -> None:
        # ASGI normalizes `..` segments in URLs before routing, so the path
        # `/mount/file/../../etc/passwd` becomes `/etc/passwd` and returns 404
        # (no route match).  Either 400 or 404 confirms the traversal is blocked.
        r = attach_client.get("/test/mount/file/../../etc/passwd")
        assert r.status_code in (400, 404)

    def test_file_in_subdir(self, attach_client: TestClient) -> None:
        r = attach_client.get("/test/mount/file/sub/photo.png")
        assert r.status_code == 200

    def test_permission_denied_returns_403(
        self,
        attach_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from lens.core.mount import LocalMountBackend

        def _deny(
            self: LocalMountBackend,  # noqa: ARG001
            subpath: str,  # noqa: ARG001
            *,
            start: int | None,  # noqa: ARG001
            end: int | None,  # noqa: ARG001
        ) -> Generator[bytes, None, None] | None:
            raise PermissionError("Operation not permitted")

        monkeypatch.setattr(LocalMountBackend, "stream_file_range", _deny)
        r = attach_client.get("/test/mount/file/hero.jpg")
        assert r.status_code == 403
        assert "not readable" in r.json()["detail"]


class TestAttachEndpoint:
    def test_no_mount_returns_error(self, test_client: TestClient) -> None:
        r = test_client.post("/test/attach", json={"path": "hero.jpg"})
        assert r.status_code == 200
        assert r.json()["status"] == "error"
        assert "mount_point" in r.json()["detail"]

    def test_valid_image_returns_ok(self, attach_client: TestClient) -> None:
        r = attach_client.post("/test/attach", json={"path": "hero.jpg"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["type"] == "image"
        assert "hero.jpg" in data["embed"]

    def test_video_attach_returns_ok(self, attach_client: TestClient) -> None:
        r = attach_client.post("/test/attach", json={"path": "clip.mp4"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["type"] == "video"

    def test_unsupported_extension_returns_error(self, attach_client: TestClient) -> None:
        r = attach_client.post("/test/attach", json={"path": "file.xyz"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert "unsupported" in data["detail"]

    def test_missing_file_returns_error(self, attach_client: TestClient) -> None:
        r = attach_client.post("/test/attach", json={"path": "ghost.png"})
        assert r.status_code == 200
        assert r.json()["status"] == "error"

    def test_attach_with_address_and_line_returns_ok(self, attach_client: TestClient) -> None:
        r = attach_client.post(
            "/test/attach",
            json={"path": "hero.jpg", "address": "/", "line": 1},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "hero.jpg" in data["embed"]

    def test_attach_invalid_line_returns_error(self, attach_client: TestClient) -> None:
        r = attach_client.post(
            "/test/attach",
            json={"path": "hero.jpg", "address": "/", "line": 999},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "error"
        assert "out of range" in r.json()["detail"]

    def test_attach_at_line_pushes_existing_content_down(
        self, attach_client: TestClient, tmp_path: Path
    ) -> None:
        r = attach_client.post(
            "/test/attach",
            json={"path": "hero.jpg", "address": "/", "line": 3},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        after = (tmp_path / "narrative" / "story" / "_node.md").read_text()
        assert "Opening." in after
        assert "hero.jpg" in after
        assert after.index("hero.jpg") < after.index("Opening.")

    def test_layered_attach_returns_ok(self, attach_client: TestClient) -> None:
        r = attach_client.post(
            "/test/attach", json={"path": "hero.jpg", "fg_path": "sub/photo.png"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["type"] == "image"
        assert "hero.jpg" in data["embed"]
        assert "sub/photo.png" in data["embed"]
        assert "lens-vn-composite" in data["embed"]

    def test_layered_attach_non_image_fg_returns_error(self, attach_client: TestClient) -> None:
        r = attach_client.post(
            "/test/attach", json={"path": "hero.jpg", "fg_path": "clip.mp4"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert "requires images" in data["detail"]


class TestStatsHasMount:
    def test_has_mount_false_without_config(self, test_client: TestClient) -> None:
        data = test_client.get("/test/stats").json()
        assert data["has_mount"] is False

    def test_has_mount_true_with_config(self, attach_client: TestClient) -> None:
        data = attach_client.get("/test/stats").json()
        assert data["has_mount"] is True
