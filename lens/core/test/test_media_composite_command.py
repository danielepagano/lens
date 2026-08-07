"""Tests for the ``media composite chromakey`` core command."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
import yaml

from lens.core.commands.media_composite import chromakey, chromakey_preview
from lens.core.media.apng import decode_apng, encode_palettized_png
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


def _synthetic_magenta_apng(frames: int = 4, size: int = 120) -> bytes:
    """The same stand-in illustration, animated -- a moving black square."""
    seq = []
    for i in range(frames):
        img = np.full((size, size, 4), (255, 0, 255, 255), dtype=np.uint8)
        x = 20 + i * 8
        img[40:80, x:x + 40] = (0, 0, 0, 255)
        seq.append(img)
    png, _ = encode_palettized_png(seq, [Fraction(1, 16)] * frames, loop_count=0)
    return png


class ChromakeyAnimationTests(unittest.TestCase):
    def test_preview_is_skipped_for_animated_source(self) -> None:
        """Previewing an animation would key every frame, then save would redo it.

        Reported as a normal outcome, not an error: the caller's next step is
        still save, and it should be able to tell that apart from a failure.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "loop.png").write_bytes(_synthetic_magenta_apng(4))
            session = ProjectSession(root, root)
            preview = chromakey_preview(session, "loop.png")
            self.assertTrue(preview.preview_skipped)
            self.assertEqual(preview.n_frames, 4)
            self.assertEqual(preview.png_bytes, b"")
            self.assertIsNone(preview.key_hex, "no keying ran, so no stats to report")
            self.assertIsNone(preview.core_tol)

    def test_preview_skip_does_not_write_to_the_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "loop.png").write_bytes(_synthetic_magenta_apng(4))
            session = ProjectSession(root, root)
            chromakey_preview(session, "loop.png")
            self.assertFalse((root / "media" / "loop_fg.png").exists())

    def test_preview_still_works_for_stills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "still.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)
            preview = chromakey_preview(session, "still.png")
            self.assertEqual(preview.n_frames, 1)
            self.assertFalse(preview.preview_skipped)
            self.assertGreater(len(preview.png_bytes), 0)
            self.assertIsNotNone(preview.key_hex)

    def test_save_writes_an_animated_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "loop.png").write_bytes(_synthetic_magenta_apng(4))
            session = ProjectSession(root, root)
            result = chromakey(session, "loop.png")
            self.assertEqual(result.n_frames, 4)
            self.assertIsNotNone(result.palette_colors)
            saved = (root / "media" / "loop_fg.png").read_bytes()
            self.assertIn(b"acTL", saved, "saved output must stay animated")
            decoded = decode_apng(saved)
            self.assertEqual(len(decoded.frames_bgra), 4)
            self.assertEqual(decoded.delays, [Fraction(1, 16)] * 4,
                             "authored frame rate must survive the round trip")
            self.assertEqual(decoded.frames_bgra[0][5, 5, 3], 0, "background cleared")


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

    def test_rerun_overwrites_previous_output(self) -> None:
        """The tune-and-rerun flow: same destination, different tolerance, overwritten in place."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)

            first = chromakey(session, "hero.png", key="FF00FF", core_tol=10)
            self.assertEqual(first.output_path, "hero_fg.png")

            second = chromakey(session, "hero.png", key="FF00FF", core_tol=60)
            self.assertEqual(second.output_path, "hero_fg.png")
            self.assertEqual(second.core_tol, 60)

            sidecar = yaml.safe_load((root / "media" / "hero_fg.png.yml").read_text())
            self.assertEqual(sidecar["composite"], "foreground")

    def test_preexisting_unrelated_file_at_destination_is_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            (root / "media" / "hero_fg.png").write_bytes(b"not a real png")
            session = ProjectSession(root, root)

            result = chromakey(session, "hero.png")

            self.assertEqual(result.output_path, "hero_fg.png")
            decoded = cv2.imdecode(
                np.frombuffer((root / "media" / "hero_fg.png").read_bytes(), dtype=np.uint8),
                cv2.IMREAD_UNCHANGED,
            )
            assert decoded is not None

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


class ChromakeyPreviewTests(unittest.TestCase):
    def test_preview_does_not_touch_the_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)

            preview = chromakey_preview(session, "hero.png")

            self.assertEqual(preview.key_hex, "#FF00FF")
            self.assertGreater(len(preview.png_bytes), 0)
            self.assertEqual(preview.png_bytes[:8], b"\x89PNG\r\n\x1a\n")
            self.assertFalse((root / "media" / "hero_fg.png").exists())
            self.assertFalse((root / "media" / "hero_fg.png.yml").exists())

    def test_preview_reflects_manual_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)

            preview = chromakey_preview(session, "hero.png", key="FF00FF", core_tol=60)

            self.assertEqual(preview.core_tol, 60)
            self.assertEqual(preview.n_corners_used, 0)

    def test_preview_no_mount_configured_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project_no_mount(root)
            session = ProjectSession(root, root)
            with self.assertRaises(LensException) as ctx:
                chromakey_preview(session, "hero.png")
            self.assertIn("mount_point", str(ctx.exception))

    def test_preview_then_save_produces_same_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _init_repo(Path(tmp))
            _make_project(root)
            (root / "media" / "hero.png").write_bytes(_synthetic_magenta_png())
            session = ProjectSession(root, root)

            preview = chromakey_preview(session, "hero.png", core_tol=45)
            saved = chromakey(session, "hero.png", core_tol=45)

            self.assertEqual(preview.key_hex, saved.key_hex)
            self.assertEqual(preview.core_tol, saved.core_tol)


if __name__ == "__main__":
    unittest.main()
