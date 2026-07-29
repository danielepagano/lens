"""Unit tests for lens.core.mount backends and get_mount_backend factory."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUntypedClassDecorator=false, reportUntypedFunctionDecorator=false

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest import mock

import boto3  # type: ignore[import-untyped]
from moto import mock_aws  # type: ignore[import-untyped]

from lens.core.mount import LocalMountBackend, S3MountBackend, normalize_subpath


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BUCKET = "test-bucket"
_REGION = "us-east-1"
_AWS_ENV_PREFIX = "AWS_"


@contextlib.contextmanager
def isolated_aws_env_for_moto() -> Generator[None, None, None]:
    """Clear host AWS_* env so moto is not bypassed (e.g. AWS_ENDPOINT_URL → real S3).

    Restores the previous environment after the block. Uses long dummy credentials
    so botocore never treats them as the user's real keys if a request slips past moto.
    """
    saved = {k: v for k, v in os.environ.items() if k.startswith(_AWS_ENV_PREFIX)}
    try:
        for k in list(saved.keys()):
            del os.environ[k]
        os.environ["AWS_ACCESS_KEY_ID"] = "moto-test-access-key-id-0001"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "moto-test-secret-access-key-00000000000000000001"
        os.environ["AWS_DEFAULT_REGION"] = _REGION
        yield
    finally:
        for k in list(os.environ.keys()):
            if k.startswith(_AWS_ENV_PREFIX):
                del os.environ[k]
        os.environ.update(saved)


class UsesMotoS3Env(unittest.TestCase):
    """Enter isolated AWS env before each test; pair with ``@mock_aws`` on the class."""

    def setUp(self) -> None:
        super().setUp()
        self._aws_env_cm = isolated_aws_env_for_moto()
        self._aws_env_cm.__enter__()

    def tearDown(self) -> None:
        try:
            super().tearDown()
        finally:
            cm = getattr(self, "_aws_env_cm", None)
            if cm is not None:
                cm.__exit__(None, None, None)


def _make_s3_client() -> Any:
    return boto3.client("s3", region_name=_REGION)  # type: ignore[return-value]


def _create_bucket(s3_client: Any) -> None:
    s3_client.create_bucket(Bucket=_BUCKET)


# ---------------------------------------------------------------------------
# normalize_subpath
# ---------------------------------------------------------------------------


class TestNormalizeSubpath(unittest.TestCase):

    def test_simple_path(self) -> None:
        self.assertEqual(normalize_subpath("a/b/c"), "a/b/c")

    def test_strips_leading_slash(self) -> None:
        self.assertEqual(normalize_subpath("/a/b"), "a/b")

    def test_collapses_dot_dot(self) -> None:
        self.assertEqual(normalize_subpath("a/b/../c"), "a/c")

    def test_dot_dot_past_root_clamps(self) -> None:
        self.assertEqual(normalize_subpath("../../etc/passwd"), "etc/passwd")

    def test_empty_string(self) -> None:
        self.assertEqual(normalize_subpath(""), "")

    def test_removes_dot_segments(self) -> None:
        self.assertEqual(normalize_subpath("a/./b"), "a/b")


# ---------------------------------------------------------------------------
# LocalMountBackend
# ---------------------------------------------------------------------------


class TestLocalMountBackend(unittest.TestCase):

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        root = Path(self._tmpdir)
        self._root = root
        self._backend = LocalMountBackend(root)

        # Set up directory structure
        (root / "sub").mkdir()
        (root / "hero.jpg").write_bytes(b"\xff\xd8")
        (root / "clip.mp4").write_bytes(b"\x00\x00")
        (root / "doc.pdf").write_bytes(b"%PDF")
        (root / "notes.txt").write_bytes(b"text")
        (root / ".hidden").write_bytes(b"x")
        (root / "script.sh").write_bytes(b"#!/bin/sh")
        (root / "sub" / "photo.png").write_bytes(b"\x89PNG")

    # --- list_dir ---

    def test_list_dir_root(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertIn("hero.jpg", names)
        self.assertIn("sub", names)

    def test_list_dir_dirs_first(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        kinds = ["dir" if e["is_dir"] else "file" for e in entries]
        dir_idxs = [i for i, k in enumerate(kinds) if k == "dir"]
        file_idxs = [i for i, k in enumerate(kinds) if k == "file"]
        if dir_idxs and file_idxs:
            self.assertLess(max(dir_idxs), min(file_idxs))

    def test_list_dir_hidden_excluded(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertNotIn(".hidden", names)

    def test_list_dir_unsupported_ext_excluded(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertNotIn("script.sh", names)

    def test_list_dir_subdirectory(self) -> None:
        entries = self._backend.list_dir("sub")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertIn("photo.png", names)

    def test_list_dir_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self._backend.list_dir("nonexistent"))

    def test_list_dir_file_path_returns_none(self) -> None:
        self.assertIsNone(self._backend.list_dir("hero.jpg"))

    def test_list_dir_traversal_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._backend.list_dir("../../etc")

    # --- stream_file ---

    def test_stream_file_returns_bytes(self) -> None:
        result = self._backend.stream_file("hero.jpg")
        self.assertIsNotNone(result)
        assert result is not None
        stream, _ = result
        data = b"".join(stream)
        self.assertEqual(data, b"\xff\xd8")

    def test_stream_file_content_type_jpg(self) -> None:
        result = self._backend.stream_file("hero.jpg")
        self.assertIsNotNone(result)
        assert result is not None
        _, ct = result
        self.assertIn("jpeg", ct)

    def test_stream_file_missing_returns_none(self) -> None:
        self.assertIsNone(self._backend.stream_file("ghost.jpg"))

    def test_stream_file_traversal_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._backend.stream_file("../../etc/passwd")

    def test_stream_file_permission_denied_raises_before_iteration(self) -> None:
        with mock.patch.object(Path, "open", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self._backend.stream_file("hero.jpg")

    # --- file_exists ---

    def test_file_exists_true(self) -> None:
        self.assertTrue(self._backend.file_exists("hero.jpg"))

    def test_file_exists_false(self) -> None:
        self.assertFalse(self._backend.file_exists("ghost.jpg"))

    def test_file_exists_dir_returns_false(self) -> None:
        self.assertFalse(self._backend.file_exists("sub"))

    def test_file_exists_traversal_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._backend.file_exists("../../etc/passwd")

    def test_stream_file_range_permission_denied_raises_before_iteration(self) -> None:
        with mock.patch.object(Path, "open", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self._backend.stream_file_range("hero.jpg", start=None, end=None)

    # --- put_file ---

    def test_put_file_creates_file(self) -> None:
        data = io.BytesIO(b"image data")
        rel = self._backend.put_file("", "new.jpg", data)
        self.assertTrue((self._root / "new.jpg").exists())
        self.assertEqual(rel, "new.jpg")

    def test_put_file_creates_subdir(self) -> None:
        data = io.BytesIO(b"x")
        self._backend.put_file("newdir", "img.png", data)
        self.assertTrue((self._root / "newdir" / "img.png").exists())

    def test_put_file_conflict_raises(self) -> None:
        data = io.BytesIO(b"x")
        with self.assertRaises(FileExistsError):
            self._backend.put_file("", "hero.jpg", data)

    # --- delete ---

    def test_delete_file(self) -> None:
        result = self._backend.delete("hero.jpg")
        self.assertEqual(result, "file")
        self.assertFalse((self._root / "hero.jpg").exists())

    def test_delete_empty_dir(self) -> None:
        (self._root / "emptydir").mkdir()
        result = self._backend.delete("emptydir")
        self.assertEqual(result, "dir")
        self.assertFalse((self._root / "emptydir").exists())

    def test_delete_nonempty_dir_raises(self) -> None:
        with self.assertRaises(OSError):
            self._backend.delete("sub")

    def test_delete_missing_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self._backend.delete("ghost.jpg")

    # --- move ---

    def test_move_file(self) -> None:
        result = self._backend.move("hero.jpg", "renamed.jpg")
        self.assertEqual(result, "renamed.jpg")
        self.assertFalse((self._root / "hero.jpg").exists())
        self.assertTrue((self._root / "renamed.jpg").exists())

    def test_move_into_subdir(self) -> None:
        self._backend.move("hero.jpg", "sub/hero.jpg")
        self.assertFalse(self._backend.file_exists("hero.jpg"))
        self.assertTrue(self._backend.file_exists("sub/hero.jpg"))

    def test_move_missing_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self._backend.move("ghost.jpg", "other.jpg")

    def test_move_conflict_raises(self) -> None:
        with self.assertRaises(FileExistsError):
            self._backend.move("hero.jpg", "notes.txt")

    def test_move_traversal_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._backend.move("../../etc/passwd", "safe.txt")

    # --- delete_tree ---

    def test_delete_tree_removes_nested_files(self) -> None:
        (self._root / "tree").mkdir()
        (self._root / "tree" / "a.mp3").write_bytes(b"a")
        (self._root / "tree" / "nested").mkdir()
        (self._root / "tree" / "nested" / "b.mp3").write_bytes(b"b")
        self._backend.delete_tree("tree")
        self.assertFalse((self._root / "tree").exists())

    def test_delete_tree_single_file(self) -> None:
        self._backend.delete_tree("hero.jpg")
        self.assertFalse((self._root / "hero.jpg").exists())

    def test_delete_tree_missing_noop(self) -> None:
        self._backend.delete_tree("ghost-dir")

    def test_delete_tree_empty_subpath_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._backend.delete_tree("")

    # --- move_tree ---

    def test_move_tree_moves_directory(self) -> None:
        (self._root / "orig").mkdir()
        (self._root / "orig" / "x.mp3").write_bytes(b"x")
        self._backend.move_tree("orig", "renamed")
        self.assertFalse((self._root / "orig").exists())
        self.assertTrue((self._root / "renamed" / "x.mp3").exists())

    def test_move_tree_missing_noop(self) -> None:
        self._backend.move_tree("nope", "also-nope")
        self.assertFalse((self._root / "also-nope").exists())

    def test_move_tree_dst_exists_raises(self) -> None:
        (self._root / "t1").mkdir()
        (self._root / "t2").mkdir()
        with self.assertRaises(FileExistsError):
            self._backend.move_tree("t1", "t2")

    # --- walk_all ---

    def test_walk_all_returns_all_files(self) -> None:
        files = self._backend.walk_all("")
        self.assertIn("hero.jpg", files)
        self.assertIn("clip.mp4", files)
        self.assertIn("doc.pdf", files)
        self.assertIn("notes.txt", files)
        self.assertIn("sub/photo.png", files)
        # hidden and unsupported are excluded
        self.assertNotIn(".hidden", files)
        self.assertNotIn("script.sh", files)

    def test_walk_all_empty_dir(self) -> None:
        empty = Path(tempfile.mkdtemp())
        backend = LocalMountBackend(empty)
        self.assertEqual(backend.walk_all(""), [])

    def test_walk_all_subpath(self) -> None:
        files = self._backend.walk_all("sub")
        self.assertEqual(files, ["sub/photo.png"])

    def test_walk_all_file_path_returns_empty(self) -> None:
        self.assertEqual(self._backend.walk_all("hero.jpg"), [])


# ---------------------------------------------------------------------------
# S3MountBackend
# ---------------------------------------------------------------------------


@mock_aws
class TestS3MountBackend(UsesMotoS3Env):

    def setUp(self) -> None:
        super().setUp()
        self._s3: Any = _make_s3_client()
        _create_bucket(self._s3)
        self._backend = S3MountBackend(_BUCKET, "", self._s3)

        # Seed objects
        self._s3.put_object(Bucket=_BUCKET, Key="hero.jpg", Body=b"\xff\xd8", ContentType="image/jpeg")
        self._s3.put_object(Bucket=_BUCKET, Key="clip.mp4", Body=b"\x00\x00", ContentType="video/mp4")
        self._s3.put_object(Bucket=_BUCKET, Key="sub/photo.png", Body=b"\x89PNG", ContentType="image/png")
        self._s3.put_object(Bucket=_BUCKET, Key=".hidden", Body=b"x", ContentType="application/octet-stream")
        self._s3.put_object(Bucket=_BUCKET, Key="script.sh", Body=b"#!/bin/sh", ContentType="text/x-sh")

    # --- list_dir ---

    def test_list_dir_root(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertIn("hero.jpg", names)
        self.assertIn("sub", names)

    def test_list_dir_hidden_excluded(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertNotIn(".hidden", names)

    def test_list_dir_unsupported_ext_excluded(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertNotIn("script.sh", names)

    def test_list_dir_subdirectory(self) -> None:
        entries = self._backend.list_dir("sub")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertIn("photo.png", names)

    def test_list_dir_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self._backend.list_dir("nonexistent"))

    def test_list_dir_dirs_before_files(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        kinds = ["dir" if e["is_dir"] else "file" for e in entries]
        dir_idxs = [i for i, k in enumerate(kinds) if k == "dir"]
        file_idxs = [i for i, k in enumerate(kinds) if k == "file"]
        if dir_idxs and file_idxs:
            self.assertLess(max(dir_idxs), min(file_idxs))

    # --- stream_file ---

    def test_stream_file_returns_bytes(self) -> None:
        result = self._backend.stream_file("hero.jpg")
        self.assertIsNotNone(result)
        assert result is not None
        stream, _ = result
        data = b"".join(stream)
        self.assertEqual(data, b"\xff\xd8")

    def test_stream_file_content_type(self) -> None:
        result = self._backend.stream_file("hero.jpg")
        self.assertIsNotNone(result)
        assert result is not None
        _, ct = result
        self.assertIn("jpeg", ct)

    def test_stream_file_missing_returns_none(self) -> None:
        self.assertIsNone(self._backend.stream_file("ghost.jpg"))

    # --- file_exists ---

    def test_file_exists_true(self) -> None:
        self.assertTrue(self._backend.file_exists("hero.jpg"))

    def test_file_exists_false(self) -> None:
        self.assertFalse(self._backend.file_exists("ghost.jpg"))

    # --- put_file ---

    def test_put_file_uploads_object(self) -> None:
        data = io.BytesIO(b"new image")
        rel = self._backend.put_file("", "new.jpg", data)
        self.assertEqual(rel, "new.jpg")
        obj: Any = self._s3.get_object(Bucket=_BUCKET, Key="new.jpg")
        self.assertEqual(obj["Body"].read(), b"new image")

    def test_put_file_in_subdir(self) -> None:
        data = io.BytesIO(b"x")
        rel = self._backend.put_file("uploads", "pic.png", data)
        self.assertEqual(rel, "uploads/pic.png")
        self._s3.head_object(Bucket=_BUCKET, Key="uploads/pic.png")

    def test_put_file_conflict_raises(self) -> None:
        data = io.BytesIO(b"x")
        with self.assertRaises(FileExistsError):
            self._backend.put_file("", "hero.jpg", data)

    # --- delete ---

    def test_delete_file(self) -> None:
        result = self._backend.delete("hero.jpg")
        self.assertEqual(result, "file")
        self.assertFalse(self._backend.file_exists("hero.jpg"))

    def test_delete_empty_prefix(self) -> None:
        # S3 has no real directories — deleting an empty "dir" prefix returns "dir"
        result = self._backend.delete("emptydir")
        self.assertEqual(result, "dir")

    def test_delete_nonempty_prefix_raises(self) -> None:
        with self.assertRaises(OSError):
            self._backend.delete("sub")

    # --- move ---

    def test_move_file(self) -> None:
        result = self._backend.move("hero.jpg", "renamed.jpg")
        self.assertEqual(result, "renamed.jpg")
        self.assertFalse(self._backend.file_exists("hero.jpg"))
        self.assertTrue(self._backend.file_exists("renamed.jpg"))

    def test_move_missing_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self._backend.move("ghost.jpg", "other.jpg")

    def test_move_conflict_raises(self) -> None:
        with self.assertRaises(FileExistsError):
            self._backend.move("hero.jpg", "clip.mp4")

    def test_delete_tree_removes_objects(self) -> None:
        self._s3.put_object(Bucket=_BUCKET, Key="tree/a.mp3", Body=b"a")
        self._s3.put_object(Bucket=_BUCKET, Key="tree/sub/b.mp3", Body=b"b")
        self._backend.delete_tree("tree")
        self.assertFalse(self._backend.file_exists("tree/a.mp3"))
        self.assertFalse(self._backend.file_exists("tree/sub/b.mp3"))

    def test_delete_tree_missing_noop(self) -> None:
        self._backend.delete_tree("ghost")

    def test_move_tree_moves_prefix(self) -> None:
        self._s3.put_object(Bucket=_BUCKET, Key="old/x.mp3", Body=b"x")
        self._backend.move_tree("old", "new")
        self.assertFalse(self._backend.file_exists("old/x.mp3"))
        self.assertTrue(self._backend.file_exists("new/x.mp3"))

    # --- walk_all ---

    def test_walk_all_returns_all_files(self) -> None:
        files = self._backend.walk_all("")
        self.assertIn("hero.jpg", files)
        self.assertIn("clip.mp4", files)
        self.assertIn("sub/photo.png", files)
        self.assertNotIn(".hidden", files)
        self.assertNotIn("script.sh", files)

    def test_walk_all_subpath(self) -> None:
        files = self._backend.walk_all("sub")
        self.assertEqual(files, ["sub/photo.png"])

    def test_walk_all_file_path_returns_empty(self) -> None:
        self.assertEqual(self._backend.walk_all("hero.jpg"), [])


# ---------------------------------------------------------------------------
# S3MountBackend with prefix
# ---------------------------------------------------------------------------


@mock_aws
class TestS3MountBackendWithPrefix(UsesMotoS3Env):

    def setUp(self) -> None:
        super().setUp()
        self._s3: Any = _make_s3_client()
        _create_bucket(self._s3)
        self._backend = S3MountBackend(_BUCKET, "media/", self._s3)
        self._s3.put_object(Bucket=_BUCKET, Key="media/hero.jpg", Body=b"\xff\xd8", ContentType="image/jpeg")

    def test_list_dir_respects_prefix(self) -> None:
        entries = self._backend.list_dir("")
        self.assertIsNotNone(entries)
        assert entries is not None
        names = {e["name"] for e in entries}
        self.assertIn("hero.jpg", names)

    def test_file_exists_with_prefix(self) -> None:
        self.assertTrue(self._backend.file_exists("hero.jpg"))
        self.assertFalse(self._backend.file_exists("ghost.jpg"))

    def test_put_file_uses_prefix(self) -> None:
        data = io.BytesIO(b"x")
        self._backend.put_file("", "new.png", data)
        self._s3.head_object(Bucket=_BUCKET, Key="media/new.png")

    def test_walk_all_respects_prefix(self) -> None:
        files = self._backend.walk_all("")
        self.assertEqual(files, ["hero.jpg"])


# ---------------------------------------------------------------------------
# get_mount_backend factory
# ---------------------------------------------------------------------------


class TestGetMountBackend(unittest.TestCase):

    def test_none_when_not_configured(self) -> None:
        from lens.core.project import get_mount_backend
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nnarrative = "story"\n')
            self.assertIsNone(get_mount_backend(p))

    def test_local_backend_for_relative_path(self) -> None:
        from lens.core.project import get_mount_backend
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "media"\n')
            backend = get_mount_backend(p)
            self.assertIsInstance(backend, LocalMountBackend)

    def test_local_backend_for_absolute_path(self) -> None:
        from lens.core.project import get_mount_backend
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            abs_path = str(p / "mnt")
            (p / "lens.toml").write_text(f'[project]\nmount_point = "{abs_path}"\n')
            backend = get_mount_backend(p)
            self.assertIsInstance(backend, LocalMountBackend)

    def test_s3_backend_for_s3_uri(self) -> None:
        from lens.core.project import get_mount_backend
        with isolated_aws_env_for_moto(), mock_aws():
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)
                (p / "lens.toml").write_text('[project]\nmount_point = "s3://my-bucket"\n')
                backend = get_mount_backend(p)
                self.assertIsInstance(backend, S3MountBackend)

    def test_s3_backend_uri_with_prefix(self) -> None:
        from lens.core.project import get_mount_backend
        with isolated_aws_env_for_moto(), mock_aws():
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)
                (p / "lens.toml").write_text(
                    '[project]\nmount_point = "s3://my-bucket/media"\n'
                )
                backend = get_mount_backend(p)
                self.assertIsInstance(backend, S3MountBackend)
                assert isinstance(backend, S3MountBackend)
                self.assertEqual(backend.bucket, "my-bucket")
                self.assertEqual(backend.prefix, "media/")

    def test_none_when_no_lens_toml(self) -> None:
        from lens.core.project import get_mount_backend
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(get_mount_backend(Path(tmp)))

    def test_get_mount_point_returns_none_for_s3_uri(self) -> None:
        from lens.core.project import get_mount_point
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "s3://bucket"\n')
            self.assertIsNone(get_mount_point(p))

    def test_has_mount_config_false_when_missing(self) -> None:
        from lens.core.project import has_mount_config
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nnarrative = "story"\n')
            self.assertFalse(has_mount_config(p))

    def test_has_mount_config_true_for_local(self) -> None:
        from lens.core.project import has_mount_config
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "media"\n')
            self.assertTrue(has_mount_config(p))

    def test_has_mount_config_true_for_s3(self) -> None:
        from lens.core.project import has_mount_config
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "s3://bucket"\n')
            self.assertTrue(has_mount_config(p))

    def test_is_cloud_mount_config(self) -> None:
        from lens.core.project import is_cloud_mount_config
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.assertFalse(is_cloud_mount_config(p))
            (p / "lens.toml").write_text('[project]\nmount_point = "media"\n')
            self.assertFalse(is_cloud_mount_config(p))
            (p / "lens.toml").write_text('[project]\nmount_point = "s3://b/p"\n')
            self.assertTrue(is_cloud_mount_config(p))


class TestCloudDeployed(unittest.TestCase):
    def test_is_cloud_deployed_unset(self) -> None:
        from lens.core.project import is_cloud_deployed

        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LENS_CLOUD_DEPLOYED", None)
            self.assertFalse(is_cloud_deployed())

    def test_is_cloud_deployed_truthy(self) -> None:
        from lens.core.project import is_cloud_deployed

        for value in ("1", "true", "TRUE", "yes"):
            with self.subTest(value=value):
                with mock.patch.dict(os.environ, {"LENS_CLOUD_DEPLOYED": value}):
                    self.assertTrue(is_cloud_deployed())

    def test_is_cloud_deployed_falsey(self) -> None:
        from lens.core.project import is_cloud_deployed

        for value in ("0", "false", "no", ""):
            with self.subTest(value=value):
                with mock.patch.dict(os.environ, {"LENS_CLOUD_DEPLOYED": value}):
                    self.assertFalse(is_cloud_deployed())

    def test_require_cloud_compatible_mount_local_ok_without_env(self) -> None:
        from lens.core.project import require_cloud_compatible_mount

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "media"\n')
            with mock.patch.dict(os.environ, {}, clear=True):
                os.environ.pop("LENS_CLOUD_DEPLOYED", None)
                require_cloud_compatible_mount(p)

    def test_require_cloud_compatible_mount_rejects_local_on_cloud(self) -> None:
        from lens.core.exceptions import LensException
        from lens.core.project import require_cloud_compatible_mount

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "media"\n')
            with mock.patch.dict(os.environ, {"LENS_CLOUD_DEPLOYED": "1"}):
                with self.assertRaises(LensException) as ctx:
                    require_cloud_compatible_mount(p)
                self.assertIn("s3://", str(ctx.exception))
                self.assertIn("cloud deployment", str(ctx.exception))

    def test_require_cloud_compatible_mount_allows_s3_on_cloud(self) -> None:
        from lens.core.project import require_cloud_compatible_mount

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "s3://bucket"\n')
            with mock.patch.dict(os.environ, {"LENS_CLOUD_DEPLOYED": "1"}):
                require_cloud_compatible_mount(p)

    def test_get_mount_backend_rejects_local_on_cloud(self) -> None:
        from lens.core.exceptions import LensException
        from lens.core.project import get_mount_backend

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "media"\n')
            (p / "media").mkdir()
            with mock.patch.dict(os.environ, {"LENS_CLOUD_DEPLOYED": "1"}):
                with self.assertRaises(LensException):
                    get_mount_backend(p)

    def test_require_s3_mount_when_configured_for_deploy(self) -> None:
        from lens.core.exceptions import LensException
        from lens.core.project import require_s3_mount_when_configured

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "lens.toml").write_text('[project]\nmount_point = "media"\n')
            with self.assertRaises(LensException) as ctx:
                require_s3_mount_when_configured(p, slug="my-game", context="deploy")
            self.assertIn("my-game", str(ctx.exception))
            self.assertIn("deploy", str(ctx.exception))
