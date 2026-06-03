"""Tests for POST /{project}/generate (non-streaming error paths)."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from lens.core.project import ProjectSession
from lens.server.main import create_app
from lens.testing.fake_image import FakeImageServer


def _init_repo(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)


@contextmanager
def _local_mount_client() -> Generator[TestClient, None, None]:
    with FakeImageServer(processing_polls=0) as server:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "lens.toml").write_text(
                f"""
[project]
narrative = "story"
mount_point = "media"

[[image]]
api = "a2e"
model = "a2e"
api_key_env = "FAKE_IMG_KEY"
base_url = "{server.base_url}"
aspect_ratios = ["1:1"]
sizes = ["1k"]
max_prompt_chars = 200
max_batch = 4
""",
                encoding="utf-8",
            )
            narrative = root / "narrative" / "story"
            narrative.mkdir(parents=True)
            (narrative / "_node.md").write_text("# S\n", encoding="utf-8")
            (root / "knowledge").mkdir(exist_ok=True)
            (root / "media").mkdir(exist_ok=True)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init", "--no-gpg-sign"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            session = ProjectSession(root, root)
            app = create_app({"t": session})
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                with TestClient(app) as client:
                    yield client


def test_post_generate_refs_with_local_mount_returns_400() -> None:
    with _local_mount_client() as client:
        response = client.post(
            "/t/generate",
            json={"prompt": "hi", "refs": ["x.png"]},
        )
    assert response.status_code == 400
    assert "s3" in response.json()["detail"].lower()


def test_post_generate_from_alias_is_accepted() -> None:
    with _local_mount_client() as client:
        response = client.post(
            "/t/generate",
            json={"from": "missing.sidecar.json"},
        )
    assert response.status_code == 400
    assert response.json()["detail"]
