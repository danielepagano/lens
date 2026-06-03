"""Tests for ``prepare_batch`` and ``save_generated_item`` (incremental saves)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lens.core.commands.generate import (
    prepare_batch,
    read_batch_sidecar,
    save_generated_item,
)
from lens.core.exceptions import LensException
from lens.core.image.api import a2e as a2e_mod
from lens.core.project import ProjectSession
from lens.testing.fake_image import FakeImageServer


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
    return tmp


def _make_project(tmp: Path, fake_url: str, *, max_prompt_chars: int = 200) -> Path:
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


class _FastPolling:
    def __enter__(self) -> None:
        self._a = a2e_mod.INITIAL_POLL_DELAY
        self._b = a2e_mod.MAX_POLL_DELAY
        a2e_mod.INITIAL_POLL_DELAY = 0.01
        a2e_mod.MAX_POLL_DELAY = 0.02

    def __exit__(self, *_: object) -> None:
        a2e_mod.INITIAL_POLL_DELAY = self._a
        a2e_mod.MAX_POLL_DELAY = self._b


class PrepareAndSaveTests(unittest.TestCase):
    def test_raw_prompt_too_long_prepare_batch(self) -> None:
        with FakeImageServer() as _server, tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root, "http://127.0.0.1:9", max_prompt_chars=10)
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                session = ProjectSession(root, root)
                with self.assertRaises(LensException) as ctx:
                    prepare_batch(
                        session, "x" * 20, aspect="1:1", size="1k", batch=1, slug="s"
                    )
                self.assertIn("raw prompt", str(ctx.exception))

    def test_save_incremental_same_batch_creates_sidecar_once(self) -> None:
        with _FastPolling(), tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root, "http://127.0.0.1:9")
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                session = ProjectSession(root, root)
                plan, _ = prepare_batch(
                    session,
                    "a prompt",
                    aspect="1:1",
                    size="1k",
                    batch=1,
                    slug="lazy-save",
                )
            png1 = b"\x89PNG\r\n\x1a\n"
            png2 = b"\x89PNG\r\n\x1a\n\x00"
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                session = ProjectSession(root, root)
                a = save_generated_item(
                    session, plan, item_data=png1, ext="png", batch_seq=None
                )
            self.assertEqual(a.result_seq, 1)
            self.assertTrue(a.sidecar_created)
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                session = ProjectSession(root, root)
                b = save_generated_item(
                    session, plan, item_data=png2, ext="png", batch_seq=a.batch_seq
                )
            self.assertEqual(b.result_seq, 2)
            self.assertFalse(b.sidecar_created)
            self.assertEqual(a.batch_seq, b.batch_seq)
            d = root / "media" / "generated" / "lazy-save"
            self.assertTrue((d / "b_1_r_1.png").exists())
            self.assertTrue((d / "b_1_r_2.png").exists())
            self.assertTrue((d / "b_1.yaml").exists())
            sc = read_batch_sidecar(d / "b_1.yaml")
            self.assertEqual(sc.batch_size, 1)
            self.assertEqual(sc.model_id, "[default]")

    def test_save_second_batch_increments_sidecar(self) -> None:
        with _FastPolling(), tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root, "http://127.0.0.1:9")
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                session = ProjectSession(root, root)
                p1, _ = prepare_batch(
                    session, "a", aspect="1:1", size="1k", batch=1, slug="two-b"
                )
            png = b"\x89PNG\r\n\x1a\n"
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                session = ProjectSession(root, root)
                s1 = save_generated_item(
                    session, p1, item_data=png, ext="png", batch_seq=None
                )
            self.assertEqual(s1.batch_seq, 1)
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                session = ProjectSession(root, root)
                p2, _ = prepare_batch(
                    session, "b", aspect="1:1", size="1k", batch=1, slug="two-b"
                )
            with mock.patch.dict(os.environ, {"FAKE_IMG_KEY": "sk_test"}):
                session = ProjectSession(root, root)
                s2 = save_generated_item(
                    session, p2, item_data=png, ext="png", batch_seq=None
                )
            self.assertEqual(s2.batch_seq, 2)
            d = root / "media" / "generated" / "two-b"
            self.assertTrue((d / "b_1.yaml").exists())
            self.assertTrue((d / "b_2.yaml").exists())


if __name__ == "__main__":
    unittest.main()
