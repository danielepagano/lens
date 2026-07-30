"""Tests for the ``media-composite chromakey`` core command."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
import yaml

from lens.core.commands.media_composite import chromakey
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession


def _init_repo(tmp: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, check=True)
    return tmp


def _make_project(tmp: Path) -> Path:
    (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\nmount_point = "media"\n')
    narrative_dir = tmp / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# Story\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    (tmp / "media").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)
    return tmp


def _make_project_no_mount(tmp: Path) -> Path:
    (tmp / "lens.toml").write_text('[project]\nnarrative = "story"\n')
    narrative_dir = tmp / "narrative" / "story"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "_node.md").write_text("# Story\n")
    (tmp / "knowledge").mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True)
    return tmp


def _synthetic_magenta_png(size: int = 200, square: int = 100) -> bytes:
    """Flat magenta background with a solid black square -- a stand-in
    illustration with a chroma-keyed background."""
    img = np.full((size, size, 3), (255, 0, 255), dtype=np.uint8)  # BGR magenta
    lo, hi = size // 2 - square // 2, size // 2 + square // 2
    img[lo:hi, lo:hi] = (0, 0, 0)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


class ChromakeyCommandTests(unittest.TestCase):
    def test_no_mount_configured_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project_no_mount(root)
            session = ProjectSession(root, root)
            with self.assertRaises(LensException) as ctx:
                chromakey(session, "hero.png")
            self.assertIn("mount_point", str(ctx.exception))

    def test_unsupported_extension_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "notes.txt").write_text("hi")
            session = ProjectSession(root, root)
            with self.assertRaises(LensException) as ctx:
                chromakey(session, "notes.txt")
            self.assertIn("unsupported extension", str(ctx.exception))

    def test_source_file_not_found_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            session = ProjectSession(root, root)
            with self.assertRaises(LensException) as ctx:
                chromakey(session, "missing.png")
            self.assertIn("not found", str(ctx.exception))

    def test_default_out_path_and_composite_metadata_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)

            result = chromakey(session, "hero.png")

            self.assertTrue(result.saved)
            self.assertEqual(result.output_path, "hero_fg.png")
            out_file = root / "media" / "hero_fg.png"
            self.assertTrue(out_file.exists())
            decoded = cv2.imdecode(
                np.frombuffer(out_file.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED
            )
            assert decoded is not None
            self.assertEqual(decoded.shape[2], 4)  # has alpha channel

            sidecar = yaml.safe_load((root / "media" / "hero_fg.png.yml").read_text())
            self.assertEqual(sidecar["composite"], "foreground")
            self.assertEqual(result.key_hex, "#FF00FF")

    def test_custom_out_path_in_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)

            result = chromakey(session, "hero.png", out_path="chars/hero_cut.png")

            self.assertEqual(result.output_path, "chars/hero_cut.png")
            self.assertTrue((root / "media" / "chars" / "hero_cut.png").exists())
            self.assertTrue((root / "media" / "chars" / "hero_cut.png.yml").exists())

    def test_out_path_must_be_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)
            with self.assertRaises(LensException) as ctx:
                chromakey(session, "hero.png", out_path="hero_fg.jpg")
            self.assertIn(".png", str(ctx.exception))

    def test_save_fails_if_destination_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            (root / "media" / "hero_fg.png").write_bytes(b"existing")
            session = ProjectSession(root, root)
            with self.assertRaises(LensException):
                chromakey(session, "hero.png")

    def test_preview_writes_local_file_without_touching_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)

            with tempfile.TemporaryDirectory() as preview_dir:
                preview_path = Path(preview_dir) / "preview.png"
                result = chromakey(session, "hero.png", preview_path=preview_path)

                self.assertFalse(result.saved)
                self.assertEqual(result.output_path, str(preview_path))
                self.assertTrue(preview_path.exists())

            self.assertFalse((root / "media" / "hero_fg.png").exists())
            self.assertFalse((root / "media" / "hero_fg.png.yml").exists())

    def test_manual_key_hex_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)

            result = chromakey(session, "hero.png", key="FF00FF", core_tol=40)

            self.assertEqual(result.key_hex, "#FF00FF")
            self.assertEqual(result.n_corners_used, 0)  # manual key skips calibration

    def test_invalid_hex_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)
            with self.assertRaises(LensException):
                chromakey(session, "hero.png", key="not-a-color")

    def test_preview_and_out_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)
            with tempfile.TemporaryDirectory() as preview_dir:
                preview_path = Path(preview_dir) / "preview.png"
                with self.assertRaises(LensException):
                    chromakey(
                        session,
                        "hero.png",
                        preview_path=preview_path,
                        out_path="other.png",
                    )


if __name__ == "__main__":
    unittest.main()
