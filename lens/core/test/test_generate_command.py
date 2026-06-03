"""Tests for the ``media generate`` core command."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import boto3  # type: ignore[import-untyped]
import yaml
from moto import mock_aws  # type: ignore[import-untyped]

from lens.core.commands.generate import (
    generate,
    read_batch_sidecar,
    resolve_sidecar_path,
)
from lens.core.exceptions import LensException
from lens.core.image.api import a2e as a2e_mod
from lens.core.project import ProjectSession
from lens.core.test.test_mount import isolated_aws_env_for_moto
from lens.testing.fake_image import FakeImageServer


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
    return tmp


def _make_project(tmp: Path, fake_url: str, *, max_prompt_chars: int = 200) -> Path:
    """Create a minimal Lens project pointed at a fake A2E server."""
    (tmp / "lens.toml").write_text(
        f"""
[project]
narrative = "story"
mount_point = "media"

[[image]]
api = "a2e"
model = "a2e"
api_key_env = "FAKE_IMG_KEY"
base_url = "{fake_url}"
aspect_ratios = ["1:1", "16:9"]
sizes = ["1k"]
max_prompt_chars = {max_prompt_chars}
max_batch = 4
"""
    )
    narrative = tmp / "narrative" / "story"
    narrative.mkdir(parents=True)
    (narrative / "_node.md").write_text("# Story\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    (tmp / "media").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--no-gpg-sign"],
        cwd=tmp,
        check=True,
        capture_output=True,
    )
    return tmp


def _make_s3_project(tmp: Path, fake_url: str, *, max_prompt_chars: int = 200) -> Path:
    (tmp / "lens.toml").write_text(
        f"""
[project]
narrative = "story"
mount_point = "s3://test-bucket/mount/"

[[image]]
api = "a2e"
model = "a2e"
api_key_env = "FAKE_IMG_KEY"
base_url = "{fake_url}"
aspect_ratios = ["1:1", "16:9"]
sizes = ["1k"]
max_prompt_chars = {max_prompt_chars}
max_batch = 4
"""
    )
    narrative = tmp / "narrative" / "story"
    narrative.mkdir(parents=True)
    (narrative / "_node.md").write_text("# Story\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--no-gpg-sign"],
        cwd=tmp,
        check=True,
        capture_output=True,
    )
    return tmp


class _FastPolling:
    def __enter__(self) -> None:
        self._a = a2e_mod.INITIAL_POLL_DELAY
        self._b = a2e_mod.MAX_POLL_DELAY
        a2e_mod.INITIAL_POLL_DELAY = 0.01
        a2e_mod.MAX_POLL_DELAY = 0.02

    def __exit__(self, *_: object) -> None:
        a2e_mod.INITIAL_POLL_DELAY = self._a
        a2e_mod.MAX_POLL_DELAY = self._b


class GenerateCommandTests(unittest.TestCase):
    def test_writes_images_and_sidecar(self) -> None:
        with FakeImageServer(processing_polls=0) as server, _FastPolling():
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    result = generate(
                        session,
                        "a tiny red cube",
                        aspect="1:1",
                        size="1k",
                        batch=2,
                        slug=None,
                    )
                self.assertEqual(len(result.paths), 2)
                self.assertEqual(result.batch_seq, 1)
                # Slug derives from prompt words.
                self.assertEqual(result.slug, "a-tiny-red-cube")
                slug_dir = root / "media" / "generated" / result.slug
                self.assertTrue((slug_dir / "b_1_r_1.png").exists())
                self.assertTrue((slug_dir / "b_1_r_2.png").exists())
                sidecar = yaml.safe_load((slug_dir / "b_1.yaml").read_text())
                self.assertEqual(sidecar["batch"], 1)
                self.assertEqual(sidecar["api"], "a2e")
                self.assertEqual(sidecar["batch_size"], 2)
                self.assertEqual(sidecar["prompt"]["raw"], "a tiny red cube")
                self.assertEqual(sidecar["prompt"]["resolved"], "a tiny red cube")
                self.assertNotIn("results", sidecar)

    def test_read_batch_sidecar_roundtrip(self) -> None:
        with FakeImageServer(processing_polls=0) as server, _FastPolling():
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    generate(
                        session,
                        "a tiny red cube",
                        aspect="1:1",
                        size="1k",
                        batch=2,
                        slug=None,
                    )
                slug_dir = root / "media" / "generated" / "a-tiny-red-cube"
                sc = read_batch_sidecar(slug_dir / "b_1.yaml")
                self.assertEqual(sc.prompt, "a tiny red cube")
                self.assertEqual(sc.batch_size, 2)
                self.assertEqual(sc.slug, "a-tiny-red-cube")
                self.assertEqual(sc.aspect_ratio, "1:1")
                self.assertEqual(sc.size, "1k")

    def test_read_batch_sidecar_with_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            slug_dir = Path(tmp) / "generated" / "my-slug"
            slug_dir.mkdir(parents=True)
            p = slug_dir / "b_1.yaml"
            p.write_text(
                """batch: 1
model_id: a2e
api: a2e
model: a2e
prompt:
  raw: "hello"
  resolved: "hello"
aspect_ratio: "1:1"
size: "1k"
batch_size: 1
refs:
  - generated/other/r1.png
  - refs/x.png
""",
                encoding="utf-8",
            )
            sc = read_batch_sidecar(p)
            self.assertEqual(
                sc.ref_paths,
                ("generated/other/r1.png", "refs/x.png"),
            )

    def test_read_batch_sidecar_refs_must_be_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            slug_dir = Path(tmp) / "generated" / "my-slug"
            slug_dir.mkdir(parents=True)
            p = slug_dir / "b_1.yaml"
            p.write_text(
                """batch: 1
model_id: a2e
api: a2e
model: a2e
prompt:
  raw: "hello"
aspect_ratio: "1:1"
size: "1k"
batch_size: 1
refs:
  - 42
""",
                encoding="utf-8",
            )
            with self.assertRaises(LensException) as ctx:
                read_batch_sidecar(p)
            self.assertIn("refs", str(ctx.exception).lower())

    def test_resolve_sidecar_absolute_path_under_mount(self) -> None:
        with FakeImageServer(processing_polls=0) as server, _FastPolling():
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    generate(
                        session,
                        "hello",
                        aspect="1:1",
                        size="1k",
                        batch=1,
                        slug="rel-slug",
                    )
                abs_path = (root / "media" / "generated" / "rel-slug" / "b_1.yaml").resolve()
                resolved = resolve_sidecar_path(root, abs_path)
                self.assertEqual(resolved, abs_path)

    def test_resolve_sidecar_outside_mount_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root, "http://127.0.0.1:9")
            outside = root / "knowledge" / "outside.yaml"
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_text("x", encoding="utf-8")
            with self.assertRaises(LensException) as ctx:
                resolve_sidecar_path(root, outside.resolve())
            self.assertIn("under the configured mount", str(ctx.exception))

    def test_resolve_sidecar_path_mount_relative_echoed_shape(self) -> None:
        """CLI prints ``generated/<slug>/b_n.yaml`` relative to the mount, not the repo root."""
        with FakeImageServer(processing_polls=0) as server, _FastPolling():
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    generate(
                        session,
                        "hello",
                        aspect="1:1",
                        size="1k",
                        batch=1,
                        slug="rel-slug",
                    )
                rel = Path("generated/rel-slug/b_1.yaml")
                prev = os.getcwd()
                try:
                    os.chdir(tempfile.gettempdir())
                    resolved = resolve_sidecar_path(root, rel)
                finally:
                    os.chdir(prev)
                self.assertTrue(resolved.is_file())
                self.assertEqual(resolved, (root / "media" / rel).resolve())

    def test_regenerate_from_sidecar_params_can_override_batch(self) -> None:
        with FakeImageServer(processing_polls=0) as server, _FastPolling():
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    generate(
                        session,
                        "fox",
                        aspect="1:1",
                        size="1k",
                        batch=2,
                        slug="ov",
                    )
                    sc = read_batch_sidecar(
                        root / "media" / "generated" / "ov" / "b_1.yaml"
                    )
                    self.assertEqual(sc.batch_size, 2)
                    r2 = generate(
                        session,
                        sc.prompt,
                        aspect=sc.aspect_ratio,
                        size=sc.size,
                        batch=1,
                        slug=sc.slug,
                        negative_prompt=sc.negative_prompt,
                        model_id=sc.model_id,
                    )
                self.assertEqual(r2.batch_seq, 2)

    def test_second_call_increments_batch_seq(self) -> None:
        with FakeImageServer(processing_polls=0) as server, _FastPolling():
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    r1 = generate(
                        session,
                        "fox",
                        aspect="1:1",
                        size="1k",
                        batch=1,
                        slug="my-slug",
                    )
                    r2 = generate(
                        session,
                        "fox",
                        aspect="1:1",
                        size="1k",
                        batch=1,
                        slug="my-slug",
                    )
                self.assertEqual(r1.batch_seq, 1)
                self.assertEqual(r2.batch_seq, 2)
                slug_dir = root / "media" / "generated" / "my-slug"
                self.assertTrue((slug_dir / "b_1.yaml").exists())
                self.assertTrue((slug_dir / "b_2.yaml").exists())

    def test_raw_prompt_too_long_rejected(self) -> None:
        with FakeImageServer() as server:
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url, max_prompt_chars=20)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    with self.assertRaises(LensException) as ctx:
                        generate(
                            session,
                            "x" * 100,
                            aspect="1:1",
                            size="1k",
                            batch=1,
                            slug="slug",
                        )
                    self.assertIn("raw prompt", str(ctx.exception))

    def test_resolved_prompt_too_long_rejected(self) -> None:
        """@-expansion blowing past max_prompt_chars must reject post-resolution."""
        from lens.core.knowledge import KnowledgeStore

        with FakeImageServer() as server:
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url, max_prompt_chars=80)
                # Create a KB object and tag it 'inline' so @-expansion inlines it.
                kb_dir = root / "knowledge" / "person"
                kb_dir.mkdir(parents=True)
                long_body = "Amy " * 50  # 200 chars, well over the 80-char cap.
                (kb_dir / "amy.md").write_text(long_body)
                (root / "knowledge" / "tags.toml").write_text(
                    'tags = { inline = ["person.amy"] }\n'
                )
                KnowledgeStore.clear_registry()
                subprocess.run(
                    ["git", "add", "-A"], cwd=root, check=True, capture_output=True
                )
                subprocess.run(
                    ["git", "commit", "-m", "kb", "--no-gpg-sign"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    with self.assertRaises(LensException) as ctx:
                        generate(
                            session,
                            "render @person.amy",
                            aspect="1:1",
                            size="1k",
                            batch=1,
                            slug="slug",
                        )
                    msg = str(ctx.exception)
                    self.assertIn("resolved prompt", msg)

    def test_unsupported_aspect_rejected(self) -> None:
        with FakeImageServer() as server:
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    with self.assertRaises(LensException):
                        generate(
                            session,
                            "x",
                            aspect="9:1",
                            size="1k",
                            batch=1,
                            slug="slug",
                        )

    def test_batch_over_max_rejected(self) -> None:
        with FakeImageServer() as server:
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    with self.assertRaises(LensException):
                        generate(
                            session,
                            "x",
                            aspect="1:1",
                            size="1k",
                            batch=99,
                            slug="slug",
                        )

    def test_ref_requires_s3_mount(self) -> None:
        with FakeImageServer(processing_polls=0) as server, _FastPolling():
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    with self.assertRaises(LensException) as ctx:
                        generate(
                            session,
                            "hello",
                            aspect="1:1",
                            size="1k",
                            batch=1,
                            slug="r",
                            ref_paths=["refs/a.png"],
                        )
                    self.assertIn("s3", str(ctx.exception).lower())


@mock_aws
class GenerateCommandRefsS3Tests(unittest.TestCase):
    _REGION = "us-east-1"

    def setUp(self) -> None:
        self._aws_cm = isolated_aws_env_for_moto()
        self._aws_cm.__enter__()

    def tearDown(self) -> None:
        self._aws_cm.__exit__(None, None, None)

    def test_generate_with_refs_presigns_and_sends_input_images(self) -> None:
        s3 = boto3.client("s3", region_name=self._REGION)
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(
            Bucket="test-bucket",
            Key="mount/refs/r.png",
            Body=b"\x89PNG\r\n\x1a\n",
            ContentType="image/png",
        )
        with FakeImageServer(processing_polls=0) as server, _FastPolling():
            with tempfile.TemporaryDirectory() as tmp:
                root = _init_repo(Path(tmp))
                _make_s3_project(root, server.base_url)
                with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                    session = ProjectSession(root, root)
                    generate(
                        session,
                        "cube",
                        aspect="1:1",
                        size="1k",
                        batch=1,
                        slug="sr",
                        ref_paths=["refs/r.png"],
                    )
                self.assertEqual(len(server.start_requests), 1)
                req = server.start_requests[0]
                imgs_raw = req.get("input_images")
                self.assertIsInstance(imgs_raw, list)
                imgs = cast(list[Any], imgs_raw)
                self.assertEqual(len(imgs), 1)
                self.assertTrue(str(imgs[0]).startswith("http"))
                obj = s3.get_object(
                    Bucket="test-bucket", Key="mount/generated/sr/b_1.yaml"
                )
                sidecar = yaml.safe_load(obj["Body"].read())
                self.assertEqual(sidecar.get("refs"), ["refs/r.png"])


if __name__ == "__main__":
    unittest.main()
