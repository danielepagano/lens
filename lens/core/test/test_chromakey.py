"""Unit tests for the chromakey pixel algorithm (lens.core.media.chromakey).

Synthetic in-memory arrays only -- no files, no mount. Ported from the
reference implementation attached to issue #102.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import unittest

import cv2
import numpy as np

from lens.core.media.chromakey import (
    CalibrationError,
    DecodeError,
    calibrate,
    decode_image,
    encode_png,
    parse_hex_key,
    remove_background,
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
