"""Unit tests for the chromakey pixel algorithm (lens.core.media.chromakey).

Synthetic in-memory arrays only -- no files, no mount. Ported from the
reference implementation attached to issue #102.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import unittest
from fractions import Fraction

import cv2
import numpy as np

from lens.core.media.apng import encode_palettized_png
from lens.core.media.chromakey import (
    DITHER_SMOOTH,
    CalibrationError,
    DecodeError,
    calibrate,
    decode_animation,
    decode_image,
    encode_png,
    parse_hex_key,
    remove_background,
    remove_background_animation,
    remove_background_animation_bytes,
    remove_background_bytes,
)


def make_synthetic(
    bg_bgr: tuple[int, int, int] = (200, 30, 220),
    size: int = 200,
    square: int = 100,
    noise_patch: bool = False,
) -> np.ndarray:
    """Flat background with a solid black square in the middle: background
    disappears, character content survives. Margin around the square is kept
    generous so a zone-free interior pixel exists to test against."""
    img = np.full((size, size, 3), bg_bgr, dtype=np.uint8)
    lo, hi = size // 2 - square // 2, size // 2 + square // 2
    img[lo:hi, lo:hi] = (0, 0, 0)  # true black, exactly collinear through the origin
    if noise_patch:
        # background drifted from the exact key color, simulating real-world
        # vignette/compression noise
        img[5:15, 5:15] = (170, 60, 190)
    return img


class ChromakeyCoreTests(unittest.TestCase):
    def test_background_becomes_transparent(self) -> None:
        img = make_synthetic()
        result = remove_background(img)
        corner_alpha = result.bgra[5, 5, 3]
        self.assertLess(corner_alpha, 10)

    def test_character_stays_opaque(self) -> None:
        img = make_synthetic()
        result = remove_background(img)
        center = img.shape[0] // 2
        self.assertEqual(result.bgra[center, center, 3], 255)

    def test_calibration_detects_the_background_color(self) -> None:
        img = make_synthetic(bg_bgr=(200, 30, 220))
        calib = calibrate(img)
        assert calib is not None
        b, g, r = calib.key_bgr
        self.assertLess(abs(b - 200), 5)
        self.assertLess(abs(g - 30), 5)
        self.assertLess(abs(r - 220), 5)

    def test_manual_key_bypasses_calibration(self) -> None:
        img = make_synthetic()
        result = remove_background(img, key_bgr=(200, 30, 220), core_tol=40)
        self.assertEqual(result.n_corners_used, 0)

    def test_no_plausible_background_raises(self) -> None:
        img = np.full((80, 80, 3), (5, 5, 5), dtype=np.uint8)
        with self.assertRaises(CalibrationError):
            remove_background(img)

    def test_core_tol_override_changes_result(self) -> None:
        img = make_synthetic(noise_patch=True)
        key = (200, 30, 220)
        tight = remove_background(img, key_bgr=key, core_tol=5)
        loose = remove_background(img, key_bgr=key, core_tol=60)
        # noise patch (distance ~46 from key) should only clear at the looser tolerance
        self.assertEqual(tight.bgra[10, 10, 3], 255)
        self.assertEqual(loose.bgra[10, 10, 3], 0)

    def test_decode_invalid_bytes_raises(self) -> None:
        with self.assertRaises(DecodeError):
            decode_image(b"not an image")

    def test_remove_background_bytes_roundtrip(self) -> None:
        img = make_synthetic()
        ok, buf = cv2.imencode(".png", img)
        self.assertTrue(ok)
        png_bytes = remove_background_bytes(buf.tobytes(), key_bgr=(200, 30, 220), core_tol=40)
        decoded = decode_image(png_bytes)
        self.assertIsNotNone(decoded)

    def test_encode_png_roundtrip(self) -> None:
        img = make_synthetic()
        result = remove_background(img, key_bgr=(200, 30, 220), core_tol=40)
        png_bytes = encode_png(result.bgra)
        self.assertGreater(len(png_bytes), 0)
        self.assertEqual(png_bytes[:8], b"\x89PNG\r\n\x1a\n")


def make_animation_bytes(
    n: int = 4, bg_bgr: tuple[int, int, int] = (200, 30, 220), size: int = 120
) -> bytes:
    """GIF bytes: the synthetic square sliding across a flat keyed background."""
    frames = []
    for i in range(n):
        img = np.full((size, size, 3), bg_bgr, dtype=np.uint8)
        x = 20 + i * 8
        img[40:80, x:x + 40] = (0, 0, 0)
        frames.append(img)
    animation = cv2.Animation()
    animation.frames = frames
    animation.durations = [60] * n
    animation.loop_count = 0
    ok, buf = cv2.imencodeanimation(".gif", animation)
    assert ok, "failed to build the test GIF"
    return buf.tobytes()


def make_apng_animation_bytes(
    n: int = 4, bg_bgr: tuple[int, int, int] = (200, 30, 220), size: int = 120
) -> bytes:
    """APNG bytes for the same synthetic animation, with no dithering.

    Built with our own encoder because OpenCV cannot write APNG -- the frames
    are opaque and few-coloured, so the palette is exact and the fixture is a
    faithful clean-source stand-in for a real APNG input.
    """
    frames = []
    for i in range(n):
        img = np.full((size, size, 4), (*bg_bgr, 255), dtype=np.uint8)
        x = 20 + i * 8
        img[40:80, x:x + 40] = (0, 0, 0, 255)
        frames.append(img)
    png, _ = encode_palettized_png(frames, [Fraction(60, 1000)] * n, loop_count=0)
    return png


class AnimationTests(unittest.TestCase):
    def test_decode_animation_reads_every_frame(self) -> None:
        decoded = decode_animation(make_animation_bytes(5))
        self.assertEqual(len(decoded.frames_bgr), 5)
        self.assertTrue(decoded.is_animated)
        self.assertEqual(decoded.delays, [Fraction(60, 1000)] * 5)
        self.assertEqual(decoded.frames_bgr[0].shape[2], 3)

    def test_decode_animation_rejects_garbage(self) -> None:
        with self.assertRaises(DecodeError):
            decode_animation(b"not an image")

    def test_still_image_decodes_as_one_frame(self) -> None:
        ok, buf = cv2.imencode(".png", make_synthetic())
        self.assertTrue(ok)
        decoded = decode_animation(buf.tobytes())
        self.assertFalse(decoded.is_animated)

    def test_keys_every_frame(self) -> None:
        decoded = decode_animation(make_animation_bytes(4))
        result = remove_background_animation(decoded.frames_bgr, decoded.delays)
        self.assertEqual(len(result.frames_bgra), 4)
        for frame in result.frames_bgra:
            self.assertEqual(frame.shape[2], 4)
            self.assertLess(frame[5, 5, 3], 10, "corner background must clear")

    def test_calibration_runs_once_for_the_whole_sequence(self) -> None:
        """Per-frame calibration lets the key drift and the cut edge shimmer."""
        decoded = decode_animation(make_animation_bytes(4))
        result = remove_background_animation(decoded.frames_bgr, decoded.delays)
        self.assertEqual(result.calibration_frame, 0)
        per_frame = [calibrate(f, smooth=DITHER_SMOOTH) for f in decoded.frames_bgr]
        assert per_frame[0] is not None
        self.assertEqual(result.key_bgr, per_frame[0].key_bgr)
        self.assertEqual(result.core_tol, per_frame[0].core_tol)

    def test_manual_key_skips_calibration_entirely(self) -> None:
        decoded = decode_animation(make_animation_bytes(3))
        result = remove_background_animation(
            decoded.frames_bgr, decoded.delays, key_bgr=(200, 30, 220), core_tol=40
        )
        self.assertEqual(result.calibration_frame, -1)
        self.assertEqual(result.n_corners_used, 0)

    def test_falls_back_to_a_later_frame_for_calibration(self) -> None:
        """A leading black fade-in frame must not sink the whole animation."""
        decoded = decode_animation(make_animation_bytes(3))
        frames = [np.zeros_like(decoded.frames_bgr[0])] + decoded.frames_bgr
        result = remove_background_animation(frames)
        self.assertEqual(result.calibration_frame, 1)

    def test_no_frame_calibrates_raises(self) -> None:
        black = [np.full((80, 80, 3), (5, 5, 5), dtype=np.uint8)] * 3
        with self.assertRaises(CalibrationError):
            remove_background_animation(black)

    def test_empty_animation_raises(self) -> None:
        with self.assertRaises(DecodeError):
            remove_background_animation([])

    def test_bytes_roundtrip_preserves_frames_and_alpha(self) -> None:
        apng = remove_background_animation_bytes(make_animation_bytes(4))
        self.assertEqual(apng[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn(b"acTL", apng, "must be an animated PNG, not a still")
        ok, animation = cv2.imdecodeanimation(np.frombuffer(apng, dtype=np.uint8))
        self.assertTrue(ok)
        self.assertEqual(len(animation.frames), 4)
        self.assertEqual(animation.frames[0].shape[2], 4, "alpha channel must survive")
        self.assertEqual(animation.frames[0][5, 5, 3], 0)

    def test_partial_alpha_survives_the_palette(self) -> None:
        """The point of APNG over GIF: fractional edge alpha, not 1-bit masking."""
        decoded = decode_animation(make_animation_bytes(3))
        result = remove_background_animation(decoded.frames_bgr, decoded.delays)
        # plant a known soft edge, then check it comes back exactly
        for frame in result.frames_bgra:
            frame[30, 30] = (0, 0, 0, 96)
        png, quantized = encode_palettized_png(
            result.frames_bgra, result.delays, loop_count=result.loop_count
        )
        self.assertIn(96, quantized.palette_alpha.tolist())
        ok, animation = cv2.imdecodeanimation(np.frombuffer(png, dtype=np.uint8))
        self.assertTrue(ok)
        self.assertEqual(int(animation.frames[0][30, 30, 3]), 96)

    def test_apng_input_roundtrips_to_apng(self) -> None:
        """The pipeline is format-agnostic on input: APNG in, keyed APNG out."""
        source = make_apng_animation_bytes(4)
        self.assertIn(b"acTL", source, "fixture must really be animated")
        decoded = decode_animation(source)
        self.assertEqual(len(decoded.frames_bgr), 4)

        out = remove_background_animation_bytes(source)
        self.assertIn(b"acTL", out)
        ok, animation = cv2.imdecodeanimation(np.frombuffer(out, dtype=np.uint8))
        self.assertTrue(ok)
        self.assertEqual(len(animation.frames), 4)
        self.assertEqual(animation.frames[0][5, 5, 3], 0, "background must clear")
        # frame 0 puts the square at rows 40:80, cols 20:60 -- sample its centre
        self.assertEqual(animation.frames[0][60, 40, 3], 255, "character must stay")

    def test_clean_apng_source_calibrates_tighter_than_dithered_gif(self) -> None:
        """Dithering, not animation, is what forces a loose tolerance."""
        clean = decode_animation(make_apng_animation_bytes(3)).frames_bgr
        dithered = decode_animation(make_animation_bytes(3)).frames_bgr
        clean_result = remove_background_animation(clean)
        dithered_result = remove_background_animation(dithered)
        self.assertLess(clean_result.core_tol, dithered_result.core_tol)
        # the undithered source recovers the true key exactly
        self.assertEqual(
            tuple(round(v) for v in clean_result.key_bgr), (200, 30, 220)
        )

    def test_dither_smoothing_is_a_noop_on_clean_sources(self) -> None:
        """The guide blur must not perturb sources that were never dithered."""
        frame = decode_animation(make_apng_animation_bytes(1)).frames_bgr[0]
        plain = calibrate(frame)
        smoothed = calibrate(frame, smooth=3)
        assert plain is not None and smoothed is not None
        self.assertEqual(plain.key_bgr, smoothed.key_bgr)
        self.assertEqual(plain.n_corners_used, smoothed.n_corners_used)
        self.assertAlmostEqual(plain.core_tol, smoothed.core_tol, delta=1.0)

    def test_calibrate_rejects_even_smoothing_kernel(self) -> None:
        with self.assertRaises(ValueError):
            calibrate(make_synthetic(), smooth=4)

    def test_loop_count_and_durations_carry_through(self) -> None:
        decoded = decode_animation(make_animation_bytes(3))
        result = remove_background_animation(
            decoded.frames_bgr, decoded.delays, loop_count=decoded.loop_count
        )
        png, _ = encode_palettized_png(
            result.frames_bgra, result.delays, loop_count=result.loop_count
        )
        ok, animation = cv2.imdecodeanimation(np.frombuffer(png, dtype=np.uint8))
        self.assertTrue(ok)
        self.assertEqual([int(d) for d in animation.durations], [60] * 3)
        self.assertEqual(int(animation.loop_count), 0)


class ParseHexKeyTests(unittest.TestCase):
    def test_parses_rrggbb_to_bgr_tuple(self) -> None:
        self.assertEqual(parse_hex_key("FF00FF"), (255.0, 0.0, 255.0))

    def test_accepts_leading_hash(self) -> None:
        self.assertEqual(parse_hex_key("#00FF00"), (0.0, 255.0, 0.0))

    def test_rejects_wrong_length(self) -> None:
        with self.assertRaises(ValueError):
            parse_hex_key("FFF")


if __name__ == "__main__":
    unittest.main()
