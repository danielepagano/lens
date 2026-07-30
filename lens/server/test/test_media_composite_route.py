"""Tests for POST /{project}/mount/composite/chromakey/{preview,save}."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import base64
import subprocess
from collections.abc import Generator
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient

from lens.core.project import ProjectSession
from lens.server.main import create_app


def _synthetic_magenta_png(size: int = 200, square: int = 100) -> bytes:
    img = np.full((size, size, 3), (255, 0, 255), dtype=np.uint8)  # BGR magenta
    lo, hi = size // 2 - square // 2, size // 2 + square // 2
    img[lo:hi, lo:hi] = (0, 0, 0)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def mount_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    (tmp_path / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "media"\n')
    narrative_dir = tmp_path / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# Story\n")
    (tmp_path / "knowledge").mkdir()
    mount = tmp_path / "media"
    mount.mkdir()
    (mount / "hero.png").write_bytes(_synthetic_magenta_png())
    (mount / "notes.txt").write_bytes(b"text")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    session = ProjectSession(tmp_path, tmp_path)
    app = create_app({"test": session})
    with TestClient(app) as client:
        yield client


class TestPreviewChromakey:
    def test_returns_png_bytes_and_stats(self, mount_client: TestClient) -> None:
        r = mount_client.post("/test/mount/composite/chromakey/preview", json={"path": "hero.png"})
        assert r.status_code == 200
        data = r.json()
        assert data["key_hex"] == "#FF00FF"
        assert data["n_corners_used"] == 4
        png_bytes = base64.b64decode(data["png_b64"])
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_does_not_write_to_the_mount(self, mount_client: TestClient, tmp_path: Path) -> None:
        r = mount_client.post("/test/mount/composite/chromakey/preview", json={"path": "hero.png"})
        assert r.status_code == 200
        assert not (tmp_path / "media" / "hero_fg.png").exists()

    def test_manual_key_and_core_tol_overrides(self, mount_client: TestClient) -> None:
        r = mount_client.post(
            "/test/mount/composite/chromakey/preview",
            json={"path": "hero.png", "key": "FF00FF", "core_tol": 60},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["core_tol"] == 60
        assert data["n_corners_used"] == 0

    def test_missing_file_returns_400(self, mount_client: TestClient) -> None:
        r = mount_client.post("/test/mount/composite/chromakey/preview", json={"path": "missing.png"})
        assert r.status_code == 400
        assert "not found" in r.json()["detail"]

    def test_unsupported_extension_returns_400(self, mount_client: TestClient) -> None:
        r = mount_client.post("/test/mount/composite/chromakey/preview", json={"path": "notes.txt"})
        assert r.status_code == 400
        assert "unsupported extension" in r.json()["detail"]

    def test_invalid_key_returns_400(self, mount_client: TestClient) -> None:
        r = mount_client.post(
            "/test/mount/composite/chromakey/preview",
            json={"path": "hero.png", "key": "nope"},
        )
        assert r.status_code == 400


class TestSaveChromakey:
    def test_saves_and_tags_composite_metadata(self, mount_client: TestClient, tmp_path: Path) -> None:
        r = mount_client.post("/test/mount/composite/chromakey/save", json={"path": "hero.png"})
        assert r.status_code == 200
        data = r.json()
        assert data["output_path"] == "hero_fg.png"
        out_file = tmp_path / "media" / "hero_fg.png"
        assert out_file.exists()
        sidecar = yaml.safe_load((tmp_path / "media" / "hero_fg.png.yml").read_text())
        assert sidecar["composite"] == "foreground"

    def test_custom_out_path(self, mount_client: TestClient, tmp_path: Path) -> None:
        r = mount_client.post(
            "/test/mount/composite/chromakey/save",
            json={"path": "hero.png", "out_path": "chars/hero_cut.png"},
        )
        assert r.status_code == 200
        assert r.json()["output_path"] == "chars/hero_cut.png"
        assert (tmp_path / "media" / "chars" / "hero_cut.png").exists()

    def test_rerun_with_new_tolerance_overwrites(self, mount_client: TestClient) -> None:
        first = mount_client.post(
            "/test/mount/composite/chromakey/save",
            json={"path": "hero.png", "key": "FF00FF", "core_tol": 10},
        )
        assert first.status_code == 200
        second = mount_client.post(
            "/test/mount/composite/chromakey/save",
            json={"path": "hero.png", "key": "FF00FF", "core_tol": 60},
        )
        assert second.status_code == 200
        assert second.json()["output_path"] == first.json()["output_path"]
        assert second.json()["core_tol"] == 60

    def test_non_png_out_path_returns_400(self, mount_client: TestClient) -> None:
        r = mount_client.post(
            "/test/mount/composite/chromakey/save",
            json={"path": "hero.png", "out_path": "hero_fg.jpg"},
        )
        assert r.status_code == 400
        assert ".png" in r.json()["detail"]
