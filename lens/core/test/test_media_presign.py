"""Tests for :mod:`lens.core.media_presign`."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import boto3  # type: ignore[import-untyped]
from moto import mock_aws  # type: ignore[import-untyped]

from lens.core.exceptions import LensException
from lens.core.media_presign import presign_mount_read_url
from lens.core.project import ProjectSession
from lens.core.test.test_mount import isolated_aws_env_for_moto

_BUCKET = "test-bucket"
_REGION = "us-east-1"


def _init_repo(tmp: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)


def _make_local_mount_project(root: Path) -> None:
    (root / "lens.toml").write_text(
        '[project]\nnarrative = "story"\nmount_point = "media"\n',
        encoding="utf-8",
    )
    (root / "narrative" / "story").mkdir(parents=True)
    (root / "narrative" / "story" / "_node.md").write_text("# S\n", encoding="utf-8")
    (root / "knowledge").mkdir(exist_ok=True)
    (root / "media").mkdir(exist_ok=True)


def _make_s3_mount_project(root: Path) -> None:
    (root / "lens.toml").write_text(
        f'[project]\nnarrative = "story"\nmount_point = "s3://{_BUCKET}/mount/"\n',
        encoding="utf-8",
    )
    (root / "narrative" / "story").mkdir(parents=True)
    (root / "narrative" / "story" / "_node.md").write_text("# S\n", encoding="utf-8")
    (root / "knowledge").mkdir(exist_ok=True)


@mock_aws
class MediaPresignTests(unittest.TestCase):
    def setUp(self) -> None:
        self._aws = isolated_aws_env_for_moto()
        self._aws.__enter__()

    def tearDown(self) -> None:
        self._aws.__exit__(None, None, None)

    def test_local_mount_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _make_local_mount_project(root)
            session = ProjectSession(root, root)
            with self.assertRaises(LensException) as ctx:
                presign_mount_read_url(session.project_root, "a.png")
            self.assertIn("s3://", str(ctx.exception))

    def test_presign_url_contains_object_path_and_sig(self) -> None:
        s3 = boto3.client("s3", region_name=_REGION)
        s3.create_bucket(Bucket=_BUCKET)
        s3.put_object(
            Bucket=_BUCKET,
            Key="mount/refs/x.png",
            Body=b"\x89PNG\r\n\x1a\n",
            ContentType="image/png",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _make_s3_mount_project(root)
            session = ProjectSession(root, root)
            url = presign_mount_read_url(session.project_root, "refs/x.png", expires_in=120)
            self.assertTrue(url.startswith("http"))
            low = url.lower()
            self.assertTrue(
                "signature=" in low
                or "x-amz-signature=" in low
                or "x-amz-credential=" in low
            )
            self.assertIn("mount/refs/x.png", url)
