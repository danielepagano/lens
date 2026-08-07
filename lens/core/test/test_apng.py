"""Unit tests for palettized (A)PNG encoding (lens.core.media.apng).

Synthetic in-memory arrays only -- no files, no mount. The container is
validated by parsing the bytes directly rather than by round-tripping through a
decoder, so a lenient reader cannot hide a spec violation from us.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import struct
import unittest
import zlib
from fractions import Fraction

import numpy as np

from lens.core.media.apng import (
    PNG_SIGNATURE,
    DELAY_MAX,
    ApngDecodeError,
    EncodeError,
    read_delay,
    png_chunk,
    decode_apng,
    encode_apng,
    encode_palettized_png,
    is_apng,
    quantize_bgra,
)


def parse_chunks(png: bytes) -> list[tuple[str, bytes]]:
    """Walk a PNG byte stream, asserting every CRC, into ``(type, data)`` pairs."""
    assert png[:8] == PNG_SIGNATURE, "missing PNG signature"
    chunks: list[tuple[str, bytes]] = []
    i = 8
    while i < len(png):
        length = int.from_bytes(png[i:i + 4], "big")
        tag = png[i + 4:i + 8]
        data = png[i + 8:i + 8 + length]
        crc = int.from_bytes(png[i + 8 + length:i + 12 + length], "big")
        assert crc == zlib.crc32(tag + data) & 0xFFFFFFFF, f"bad CRC on {tag!r}"
        chunks.append((tag.decode("latin1"), data))
        i += 12 + length
        if tag == b"IEND":
            break
    return chunks


def make_frames(n: int = 3, size: int = 32, shift: int = 4) -> list[np.ndarray]:
    """Transparent field with a moving opaque square ringed by a soft alpha edge."""
    frames: list[np.ndarray] = []
    for i in range(n):
        f = np.zeros((size, size, 4), dtype=np.uint8)
        x = 4 + i * shift
        f[8:24, x:x + 12] = (200, 80, 30, 255)
        f[7, x:x + 12] = (0, 0, 0, 128)  # partially transparent rim
        frames.append(f)
    return frames


class QuantizeTests(unittest.TestCase):
    def test_exact_palette_for_few_colors(self) -> None:
        q = quantize_bgra(make_frames())
        self.assertTrue(q.exact)
        # transparent + opaque body + soft rim
        self.assertEqual(q.n_colors, 3)

    def test_palette_sorted_by_ascending_alpha(self) -> None:
        q = quantize_bgra(make_frames())
        alpha = q.palette_alpha.tolist()
        self.assertEqual(alpha, sorted(alpha))
        self.assertEqual(alpha[0], 0, "fully transparent entry must sort first")

    def test_indices_reconstruct_original_pixels(self) -> None:
        frames = make_frames()
        q = quantize_bgra(frames)
        for original, idx in zip(frames, q.indices):
            rgb = q.palette_rgb[idx]
            self.assertTrue((rgb[..., ::-1] == original[..., :3]).all())
            self.assertTrue((q.palette_alpha[idx] == original[..., 3]).all())

    def test_bit_depth_shrinks_with_small_palette(self) -> None:
        three = quantize_bgra(make_frames())
        self.assertEqual(three.n_colors, 3)
        self.assertEqual(three.bit_depth, 2)
        many = [np.dstack([
            np.arange(256, dtype=np.uint8).reshape(16, 16) * 7 % 251,
            np.arange(256, dtype=np.uint8).reshape(16, 16) * 13 % 241,
            np.arange(256, dtype=np.uint8).reshape(16, 16) * 29 % 233,
            np.full((16, 16), 255, dtype=np.uint8),
        ])]
        self.assertEqual(quantize_bgra(many).bit_depth, 8)

    def test_kmeans_fallback_stays_within_budget(self) -> None:
        rng = np.random.default_rng(1)
        noisy = rng.integers(0, 256, (64, 64, 4), dtype=np.uint8)
        noisy[..., 3] = 255
        q = quantize_bgra([noisy], max_colors=64)
        self.assertFalse(q.exact)
        self.assertLessEqual(q.n_colors, 64)
        self.assertLess(int(q.indices[0].max()), q.n_colors)

    def test_kmeans_is_deterministic(self) -> None:
        rng = np.random.default_rng(2)
        noisy = rng.integers(0, 256, (48, 48, 4), dtype=np.uint8)
        first = quantize_bgra([noisy], max_colors=32)
        second = quantize_bgra([noisy], max_colors=32)
        self.assertTrue((first.palette_rgb == second.palette_rgb).all())
        self.assertTrue((first.indices[0] == second.indices[0]).all())

    def test_transparent_pixels_collapse_to_one_entry(self) -> None:
        """Fully transparent pixels render identically whatever colour they carry."""
        f = np.zeros((8, 8, 4), dtype=np.uint8)
        f[0, 0] = (10, 20, 30, 0)
        f[0, 1] = (200, 100, 50, 0)
        q = quantize_bgra([f])
        self.assertEqual(q.indices[0][0, 0], q.indices[0][0, 1])

    def test_rejects_mismatched_frame_sizes(self) -> None:
        with self.assertRaises(EncodeError):
            quantize_bgra([np.zeros((8, 8, 4), np.uint8), np.zeros((9, 9, 4), np.uint8)])

    def test_rejects_non_bgra(self) -> None:
        with self.assertRaises(EncodeError):
            quantize_bgra([np.zeros((8, 8, 3), np.uint8)])


def build_apng(
    frames_bgra: list[np.ndarray], dispose_op: int = 0, blend_op: int = 0, delay: Fraction = Fraction(1, 20)
) -> bytes:
    """Hand-assemble a truecolor APNG with chosen dispose/blend ops.

    Needed because :func:`encode_apng` only ever emits SOURCE/NONE, so it
    cannot produce the OVER-over-BACKGROUND shape that regressed.
    """
    h, w = frames_bgra[0].shape[:2]
    parts = [PNG_SIGNATURE, png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))]
    parts.append(png_chunk(b"acTL", struct.pack(">II", len(frames_bgra), 0)))

    def idat(frame: np.ndarray) -> bytes:
        rgba = frame[..., [2, 1, 0, 3]]  # BGRA -> RGBA
        rows = np.zeros((h, w * 4 + 1), dtype=np.uint8)
        rows[:, 1:] = rgba.reshape(h, w * 4)
        return zlib.compress(rows.tobytes(), 6)

    seq = 0
    for i, frame in enumerate(frames_bgra):
        ctl = (struct.pack(">IIIII", seq, w, h, 0, 0)
               + struct.pack(">HH", delay.numerator, delay.denominator)
               + bytes([dispose_op if i < len(frames_bgra) - 1 else 0,
                        blend_op if i else 0]))
        parts.append(png_chunk(b"fcTL", ctl))
        seq += 1
        if i == 0:
            parts.append(png_chunk(b"IDAT", idat(frame)))
        else:
            parts.append(png_chunk(b"fdAT", struct.pack(">I", seq) + idat(frame)))
            seq += 1
    parts.append(png_chunk(b"IEND", b""))
    return b"".join(parts)


class DecodeTests(unittest.TestCase):
    def test_is_apng_detects_animation(self) -> None:
        animated, _ = encode_palettized_png(make_frames(3), [Fraction(1, 25)] * 3)
        still, _ = encode_palettized_png(make_frames(1))
        self.assertTrue(is_apng(animated))
        self.assertFalse(is_apng(still))
        self.assertFalse(is_apng(b"not a png"))

    def test_rejects_non_apng(self) -> None:
        with self.assertRaises(ApngDecodeError):
            decode_apng(b"not a png at all")

    def test_roundtrip_through_our_own_encoder(self) -> None:
        frames = make_frames(4)
        png, _ = encode_palettized_png(frames, [Fraction(7, 100)] * 4, loop_count=3)
        decoded = decode_apng(png)
        self.assertEqual(len(decoded.frames_bgra), 4)
        self.assertEqual(decoded.delays, [Fraction(7, 100)] * 4)
        self.assertEqual(decoded.loop_count, 3)
        for want, got in zip(frames, decoded.frames_bgra):
            self.assertTrue((want == got).all(), "pixels must survive exactly")

    def test_over_after_background_dispose_is_not_contaminated(self) -> None:
        """Regression: OpenCV corrupts precisely this dispose/blend pairing.

        BACKGROUND clears the canvas to transparent after each frame, so an
        OVER blend onto it must yield the incoming frame untouched -- no trace
        of the frame before it.
        """
        red = np.zeros((16, 16, 4), np.uint8)
        red[..., 2] = 255
        red[..., 3] = 255
        blue = np.zeros((16, 16, 4), np.uint8)
        blue[..., 0] = 255
        blue[..., 3] = 255
        blue[0:4, 0:4, 3] = 0  # a transparent notch that must stay transparent

        decoded = decode_apng(build_apng([red, blue], dispose_op=1, blend_op=1))
        self.assertEqual(len(decoded.frames_bgra), 2)
        self.assertTrue((decoded.frames_bgra[0] == red).all())
        second = decoded.frames_bgra[1]
        self.assertTrue((second[8, 8] == (255, 0, 0, 255)).all(), "blue frame must be blue")
        self.assertEqual(
            second[1, 1, 3], 0,
            "notch must stay transparent -- red must not bleed through the dispose",
        )

    def test_dispose_none_lets_over_accumulate(self) -> None:
        """The complement: without BACKGROUND, OVER genuinely composites."""
        red = np.zeros((16, 16, 4), np.uint8)
        red[..., 2] = 255
        red[..., 3] = 255
        overlay = np.zeros((16, 16, 4), np.uint8)
        overlay[..., 0] = 255
        overlay[8:, :, 3] = 255  # opaque only on the bottom half

        decoded = decode_apng(build_apng([red, overlay], dispose_op=0, blend_op=1))
        second = decoded.frames_bgra[1]
        self.assertTrue((second[12, 8] == (255, 0, 0, 255)).all(), "bottom: overlay wins")
        self.assertTrue((second[2, 8] == (0, 0, 255, 255)).all(), "top: red shows through")

    def test_exact_frame_rate_survives_a_full_roundtrip(self) -> None:
        """1/16s is 62.5ms -- an integer-ms carrier rounds it and the loop drifts.

        Regression: the delay went out as 62/1000, making every loop run 0.8%
        fast and silently destroying an exactly-authored frame rate.
        """
        sixteenth = Fraction(1, 16)
        frames = make_frames(3)
        png, _ = encode_palettized_png(frames, [sixteenth] * 3)

        raw = [struct.unpack(">HH", d[20:24]) for t, d in parse_chunks(png) if t == "fcTL"]
        self.assertEqual(raw, [(1, 16)] * 3, "fcTL must store the fraction verbatim")

        decoded = decode_apng(png)
        self.assertEqual(decoded.delays, [sixteenth] * 3)
        self.assertEqual(sum(decoded.delays), Fraction(3, 16), "loop length is exact")

    def test_delay_too_large_for_uint16_is_approximated(self) -> None:
        png, _ = encode_palettized_png(make_frames(2), [Fraction(1, 100000)] * 2)
        decoded = decode_apng(png)
        self.assertLessEqual(decoded.delays[0].denominator, DELAY_MAX)

    def test_zero_denominator_means_hundredths(self) -> None:
        """Spec quirk: delay_den 0 is read as 100, not as a divide-by-zero."""
        self.assertEqual(read_delay(5, 0), Fraction(5, 100))

    def test_durations_and_loop_survive(self) -> None:
        f = make_frames(1)[0]
        decoded = decode_apng(build_apng([f, f.copy(), f.copy()], delay=Fraction(3, 25)))
        self.assertEqual(decoded.delays, [Fraction(3, 25)] * 3)


class ContainerTests(unittest.TestCase):
    def test_single_frame_has_no_animation_chunks(self) -> None:
        png, _ = encode_palettized_png(make_frames(1))
        types = [t for t, _ in parse_chunks(png)]
        self.assertNotIn("acTL", types)
        self.assertNotIn("fcTL", types)
        self.assertEqual(types.count("IDAT"), 1)

    def test_palette_color_type_and_trns(self) -> None:
        png, q = encode_palettized_png(make_frames())
        chunks = dict(parse_chunks(png))
        _w, _h, depth, color_type = struct.unpack(">IIBB", chunks["IHDR"][:10])
        self.assertEqual(color_type, 3, "must be a palette image")
        self.assertEqual(depth, q.bit_depth)
        self.assertEqual(len(chunks["PLTE"]), q.n_colors * 3)
        # tRNS is truncated after the last non-opaque entry
        self.assertEqual(len(chunks["tRNS"]), int(np.flatnonzero(q.palette_alpha < 255)[-1]) + 1)

    def test_trns_omitted_when_fully_opaque(self) -> None:
        opaque = np.full((8, 8, 4), 255, dtype=np.uint8)
        png, _ = encode_palettized_png([opaque])
        self.assertNotIn("tRNS", [t for t, _ in parse_chunks(png)])

    def test_actl_frame_count_and_loop(self) -> None:
        png, _ = encode_palettized_png(make_frames(5), [Fraction(1, 25)] * 5, loop_count=7)
        chunks = dict(parse_chunks(png))
        num_frames, num_plays = struct.unpack(">II", chunks["acTL"])
        self.assertEqual(num_frames, 5)
        self.assertEqual(num_plays, 7)

    def test_sequence_numbers_are_contiguous(self) -> None:
        """fcTL and fdAT share one counter; a gap makes the file invalid."""
        png, _ = encode_palettized_png(make_frames(4), [Fraction(1, 25)] * 4)
        seqs = [
            struct.unpack(">I", data[:4])[0]
            for tag, data in parse_chunks(png)
            if tag in ("fcTL", "fdAT")
        ]
        self.assertEqual(seqs, list(range(len(seqs))))

    def test_frame_count_matches_input(self) -> None:
        png, _ = encode_palettized_png(make_frames(6), [Fraction(1, 25)] * 6)
        types = [t for t, _ in parse_chunks(png)]
        self.assertEqual(types.count("fcTL"), 6)
        self.assertEqual(types.count("fdAT"), 5, "first frame rides in IDAT")

    def test_durations_encoded_as_milliseconds(self) -> None:
        png, _ = encode_palettized_png(make_frames(2), [Fraction(33, 1000), Fraction(1, 16)])
        delays = [
            struct.unpack(">HH", data[20:24])
            for tag, data in parse_chunks(png) if tag == "fcTL"
        ]
        self.assertEqual(delays, [(33, 1000), (1, 16)])

    def test_later_frames_use_change_rectangle(self) -> None:
        """A frame that only moves a small region must not re-encode the canvas."""
        frames = make_frames(2, size=64, shift=2)
        png, _ = encode_palettized_png(frames, [Fraction(1, 25), Fraction(1, 25)])
        fctls = [d for t, d in parse_chunks(png) if t == "fcTL"]
        _seq, w0, h0, _x, _y = struct.unpack(">IIIII", fctls[0][:20])
        _seq, w1, h1, x1, y1 = struct.unpack(">IIIII", fctls[1][:20])
        self.assertEqual((w0, h0), (64, 64), "first frame covers the canvas")
        self.assertLess(w1 * h1, w0 * h0)
        self.assertLessEqual(x1 + w1, 64)
        self.assertLessEqual(y1 + h1, 64)

    def test_identical_frames_emit_legal_minimum_rect(self) -> None:
        frame = make_frames(1)[0]
        png, _ = encode_palettized_png([frame, frame.copy()], [Fraction(1, 25), Fraction(1, 25)])
        fctls = [d for t, d in parse_chunks(png) if t == "fcTL"]
        _seq, w, h, _x, _y = struct.unpack(">IIIII", fctls[1][:20])
        self.assertEqual((w, h), (1, 1), "zero-area frames are invalid")

    def test_scanlines_roundtrip_at_every_bit_depth(self) -> None:
        """Sub-byte index packing must survive inflate + unpack for depths 1/2/4/8."""
        for n_colors, depth in ((2, 1), (4, 2), (16, 4), (200, 8)):
            with self.subTest(depth=depth):
                rng = np.random.default_rng(3)
                idx = rng.integers(0, n_colors, (5, 7), dtype=np.uint8)
                frame = np.zeros((5, 7, 4), dtype=np.uint8)
                # distinct opaque colours, one per index value
                frame[..., 0] = idx * (250 // max(n_colors - 1, 1))
                frame[..., 1] = 255 - frame[..., 0]
                frame[..., 3] = 255
                png, q = encode_palettized_png([frame], max_colors=256)
                self.assertEqual(q.bit_depth, depth if q.n_colors == n_colors else q.bit_depth)
                chunks = dict(parse_chunks(png))
                raw = zlib.decompress(chunks["IDAT"])
                stride = (7 * q.bit_depth + 7) // 8
                self.assertEqual(len(raw), 5 * (stride + 1))
                for row in range(5):
                    self.assertEqual(raw[row * (stride + 1)], 0, "filter type must be None")

    def test_rejects_duration_count_mismatch(self) -> None:
        with self.assertRaises(EncodeError):
            encode_apng(quantize_bgra(make_frames(3)), [Fraction(1, 25), Fraction(1, 25)])

    def test_rejects_empty_input(self) -> None:
        with self.assertRaises(EncodeError):
            quantize_bgra([])


if __name__ == "__main__":
    unittest.main()
