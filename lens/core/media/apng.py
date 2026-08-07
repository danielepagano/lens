"""Palettized (A)PNG encoding — colour type 3 with a ``tRNS`` alpha table.

Pure pixel/bytes logic, no mount or file I/O, mirroring :mod:`chromakey`.

Why palettized rather than the truecolour RGBA PNG :func:`chromakey.encode_png`
writes: for keyed *illustrations* the pixel content is a handful of flat colours
plus a thin anti-aliased rim, so a palette is near-lossless while being a
fraction of the size — close to GIF, but keeping real 8-bit alpha. PNG's
``tRNS`` chunk carries one alpha byte per palette entry, so the fractional edge
alpha that :func:`chromakey.remove_background` recovers survives, which it
cannot in GIF's single-transparent-index model.

OpenCV cannot emit APNG (``imencodeanimation`` with a ``.png``/``.apng``
extension silently writes only the first frame, with no ``acTL`` chunk), so the
container is assembled here from ``zlib`` + ``struct``.
"""

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Sequence, Tuple

import cv2
import numpy as np

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Alpha values within these margins of the extremes are snapped to fully
# transparent / fully opaque before quantization. Invisible to the eye, but it
# collapses the long tail of near-0 and near-255 values that would otherwise
# each claim a palette slot.
ALPHA_FLOOR = 2
ALPHA_CEIL = 253


class EncodeError(ValueError):
    """Raised when frames cannot be encoded as a palettized PNG."""


@dataclass(frozen=True, slots=True)
class Quantized:
    """A shared palette plus per-frame index images."""

    indices: List[np.ndarray]  # uint8 (h, w) per frame, values < len(palette)
    palette_rgb: np.ndarray    # (N, 3) uint8, RGB order (PLTE order)
    palette_alpha: np.ndarray  # (N,) uint8, parallel to palette_rgb
    exact: bool                # True if no colour loss (palette fit without k-means)

    @property
    def n_colors(self) -> int:
        return int(self.palette_rgb.shape[0])

    @property
    def bit_depth(self) -> int:
        """Smallest PNG palette bit depth that can index this palette."""
        n = self.n_colors
        if n <= 2:
            return 1
        if n <= 4:
            return 2
        if n <= 16:
            return 4
        return 8


# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------


def _pack_codes(flat_bgra: np.ndarray) -> np.ndarray:
    """(N, 4) uint8 BGRA -> (N,) uint32, so colours can be uniqued by sorting."""
    b, g, r, a = (flat_bgra[:, i].astype(np.uint32) for i in range(4))
    return (b << 24) | (g << 16) | (r << 8) | a


def _unpack_codes(codes: np.ndarray) -> np.ndarray:
    """Inverse of :func:`_pack_codes`."""
    out = np.empty((codes.shape[0], 4), dtype=np.uint8)
    for i, shift in enumerate((24, 16, 8, 0)):
        out[:, i] = ((codes >> shift) & 0xFF).astype(np.uint8)
    return out


def _premultiplied(bgra: np.ndarray) -> np.ndarray:
    """(N, 4) uint8 BGRA -> (N, 4) float32 [premul B, G, R, alpha].

    Distances are measured in premultiplied space because that is what
    compositing actually shows: two pixels agreeing on premultiplied colour and
    alpha are indistinguishable over any backdrop. It also keeps the keyed rim
    (black at partial alpha) from being merged with genuinely dark opaque paint,
    which a naive straight-RGBA distance does.
    """
    a = bgra[:, 3].astype(np.float32) / 255.0
    out = np.empty((bgra.shape[0], 4), dtype=np.float32)
    out[:, :3] = bgra[:, :3].astype(np.float32) * a[:, None]
    out[:, 3] = bgra[:, 3].astype(np.float32)
    return out


def _nearest_centre(feats: np.ndarray, centres: np.ndarray, chunk: int = 8192) -> np.ndarray:
    """Index of the closest centre for each row of *feats*, chunked to bound memory."""
    out = np.empty(feats.shape[0], dtype=np.int32)
    for start in range(0, feats.shape[0], chunk):
        block = feats[start:start + chunk]
        d = ((block[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        out[start:start + chunk] = np.argmin(d, axis=1)
    return out


def _snap_alpha(flat: np.ndarray) -> np.ndarray:
    """Snap near-extreme alpha, and zero the colour of fully transparent pixels.

    Zeroing RGB under alpha 0 matters: those pixels carry whatever colour the
    keyer left behind, and without this they would splinter into many distinct
    codes that all render identically (invisibly).
    """
    flat = flat.copy()
    a = flat[:, 3]
    a[a <= ALPHA_FLOOR] = 0
    a[a >= ALPHA_CEIL] = 255
    flat[a == 0, :3] = 0
    return flat


def quantize_bgra(frames_bgra: Sequence[np.ndarray], max_colors: int = 256) -> Quantized:
    """Build one shared palette for *frames_bgra* and index every frame against it.

    A single palette across all frames is required by the format (APNG has no
    per-frame ``PLTE``) and is what makes inter-frame diffing meaningful.

    Takes the exact palette when the distinct-colour count already fits —
    the common case for illustrations, and lossless. Otherwise falls back to
    k-means in premultiplied space over the non-transparent colours.

    Palette entries are sorted by ascending alpha so ``tRNS`` can be truncated
    after the last non-opaque entry (the PNG spec defines missing trailing
    entries as fully opaque).
    """
    if not frames_bgra:
        raise EncodeError("no frames to encode")
    if not 2 <= max_colors <= 256:
        raise EncodeError(f"max_colors must be in 2..256 (got {max_colors})")

    shapes = {f.shape[:2] for f in frames_bgra}
    if len(shapes) != 1:
        raise EncodeError(f"all frames must share one size, got {sorted(shapes)}")
    for f in frames_bgra:
        if f.ndim != 3 or f.shape[2] != 4:
            raise EncodeError("frames must be BGRA (h, w, 4)")

    h, w = frames_bgra[0].shape[:2]
    flat = _snap_alpha(np.concatenate([f.reshape(-1, 4) for f in frames_bgra]))

    codes = _pack_codes(flat)
    uniq_codes, inverse = np.unique(codes, return_inverse=True)
    uniq_bgra = _unpack_codes(uniq_codes)

    if uniq_codes.shape[0] <= max_colors:
        palette_bgra, per_pixel = uniq_bgra, inverse.astype(np.int32)
        exact = True
    else:
        palette_bgra, per_pixel = _kmeans_palette(flat, uniq_bgra, inverse, max_colors)
        exact = False

    # Sort by alpha so all non-opaque entries cluster at the front.
    order = np.argsort(palette_bgra[:, 3], kind="stable")
    palette_bgra = palette_bgra[order]
    remap = np.empty(order.shape[0], dtype=np.int32)
    remap[order] = np.arange(order.shape[0], dtype=np.int32)
    per_pixel = remap[per_pixel]

    indices = [
        per_pixel[i * h * w:(i + 1) * h * w].reshape(h, w).astype(np.uint8)
        for i in range(len(frames_bgra))
    ]
    palette_rgb = palette_bgra[:, [2, 1, 0]].copy()
    return Quantized(indices, palette_rgb, palette_bgra[:, 3].copy(), exact)


def _kmeans_palette(
    flat: np.ndarray,
    uniq_bgra: np.ndarray,
    inverse: np.ndarray,
    max_colors: int,
    sample_size: int = 120_000,
) -> Tuple[np.ndarray, np.ndarray]:
    """k-means fallback when the exact palette overflows.

    Fully transparent pixels are held out and given a single reserved entry;
    spending clusters on them would be pure waste since they all render the
    same. Training samples raw pixels (so cluster mass follows how often a
    colour actually appears), but assignment runs over the *distinct* colours
    and is projected back through ``inverse`` — far cheaper than assigning
    every pixel, and exactly equivalent.
    """
    has_transparent = bool((uniq_bgra[:, 3] == 0).any())
    reserved = 1 if has_transparent else 0
    k = max_colors - reserved

    opaque_pixels = flat[flat[:, 3] > 0]
    if opaque_pixels.shape[0] == 0:
        raise EncodeError("every pixel is fully transparent")

    # Same input must yield byte-identical output: the tune-and-rerun loop
    # overwrites the saved file, and a palette that reshuffles on every run
    # turns "I changed --core-tol" into an unreadable diff. Seeding numpy is not
    # enough -- cv2.kmeans draws its k-means++ seeds from OpenCV's own global
    # RNG, which is the only handle the binding exposes.
    cv2.setRNGSeed(0)
    rng = np.random.default_rng(0)
    if opaque_pixels.shape[0] > sample_size:
        pick = rng.choice(opaque_pixels.shape[0], sample_size, replace=False)
        sample = opaque_pixels[pick]
    else:
        sample = opaque_pixels
    k = min(k, sample.shape[0])

    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    centres = cv2.kmeans(
        _premultiplied(sample),
        k,
        np.empty((sample.shape[0], 1), dtype=np.int32),
        criteria,
        3,
        cv2.KMEANS_PP_CENTERS,
    )[2]

    # Un-premultiply the centres back into storable straight-alpha colours.
    alpha = np.clip(centres[:, 3], 0, 255)
    scale = np.where(alpha > 0.5, 255.0 / np.maximum(alpha, 0.5), 0.0)
    rgb = np.clip(centres[:, :3] * scale[:, None], 0, 255)
    palette = np.empty((k, 4), dtype=np.uint8)
    palette[:, :3] = rgb.astype(np.uint8)
    palette[:, 3] = np.rint(alpha).astype(np.uint8)

    uniq_to_entry = np.empty(uniq_bgra.shape[0], dtype=np.int32)
    visible = uniq_bgra[:, 3] > 0
    uniq_to_entry[visible] = _nearest_centre(
        _premultiplied(uniq_bgra[visible]), _premultiplied(palette)
    ) + reserved

    if has_transparent:
        palette = np.concatenate([np.zeros((1, 4), dtype=np.uint8), palette])
        uniq_to_entry[~visible] = 0

    return palette, uniq_to_entry[inverse]


# ---------------------------------------------------------------------------
# PNG / APNG container
# ---------------------------------------------------------------------------


DELAY_MAX = 0xFFFF          # fcTL stores delay_num / delay_den as uint16
DEFAULT_DELAY = Fraction(1, 10)


def read_delay(num: int, den: int) -> Fraction:
    """fcTL delay as an exact fraction of a second.

    Kept rational rather than converted to milliseconds: a source authored at
    1/16s is 62.5ms, and any integer-ms carrier silently rounds it (to 62 under
    banker's rounding), shortening every loop and destroying an exactly
    specified frame rate. Per spec a zero denominator means hundredths.
    """
    return Fraction(num, den if den else 100)


def write_delay(delay: Fraction) -> bytes:
    """Pack an exact delay into fcTL's two uint16 fields, reducing if needed."""
    if delay < 0:
        raise EncodeError(f"negative frame delay {delay}")
    if delay.numerator > DELAY_MAX or delay.denominator > DELAY_MAX:
        delay = delay.limit_denominator(DELAY_MAX)
        if delay.numerator > DELAY_MAX:
            raise EncodeError(f"frame delay {delay} does not fit in fcTL's uint16 fields")
    return struct.pack(">HH", delay.numerator, delay.denominator)


def delay_ms(delay: Fraction) -> float:
    """Exact delay rendered as milliseconds, for display only."""
    return float(delay) * 1000


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _scanlines(idx: np.ndarray, bit_depth: int) -> bytes:
    """Index image -> raw PNG scanlines, each prefixed with filter type 0.

    Palette images are left unfiltered on purpose: filters do arithmetic on
    neighbouring bytes, which is meaningless for indices (index 7 is not
    "between" 6 and 8), and the PNG spec advises against filtering them.
    """
    h, w = idx.shape
    if bit_depth == 8:
        rows = idx
    else:
        per_byte = 8 // bit_depth
        pad = (-w) % per_byte
        padded = np.zeros((h, w + pad), dtype=np.uint8)
        padded[:, :w] = idx
        bits = np.unpackbits(padded[:, :, None], axis=2)[:, :, 8 - bit_depth:]
        rows = np.packbits(bits.reshape(h, -1), axis=1)
    out = np.zeros((h, rows.shape[1] + 1), dtype=np.uint8)
    out[:, 1:] = rows
    return out.tobytes()


def _compress(raw: bytes) -> bytes:
    return zlib.compress(raw, 9)


def _changed_rect(prev: np.ndarray, cur: np.ndarray) -> Tuple[int, int, int, int]:
    """Bounding box ``(x, y, w, h)`` of pixels differing between two index frames.

    APNG frames may cover a sub-rectangle, so an animation that only moves a
    mouth or a flame re-encodes just that region. Identical frames still need a
    legal 1x1 rect — zero-sized frames are invalid.
    """
    diff = prev != cur
    if not diff.any():
        return 0, 0, 1, 1
    rows = np.flatnonzero(diff.any(axis=1))
    cols = np.flatnonzero(diff.any(axis=0))
    y0, y1 = int(rows[0]), int(rows[-1])
    x0, x1 = int(cols[0]), int(cols[-1])
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def encode_apng(
    quantized: Quantized,
    delays: Sequence[Fraction],
    *,
    loop_count: int = 0,
    default_delay: Fraction = DEFAULT_DELAY,
) -> bytes:
    """Assemble palettized PNG bytes; APNG when there is more than one frame.

    *delays* are exact durations in seconds, written to fcTL unchanged, so a
    source authored at 1/16s stays 1/16s rather than drifting through a
    rounded millisecond value.

    *loop_count* follows both GIF and APNG convention: 0 means loop forever.

    A single-frame input produces a plain still PNG with no animation chunks,
    so the same call handles both without the caller branching.
    """
    frames = quantized.indices
    if not frames:
        raise EncodeError("no frames to encode")
    if delays and len(delays) != len(frames):
        raise EncodeError(
            f"got {len(delays)} delays for {len(frames)} frames"
        )

    h, w = frames[0].shape
    depth = quantized.bit_depth
    parts = [PNG_SIGNATURE]

    parts.append(png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, 3, 0, 0, 0)))
    parts.append(png_chunk(b"PLTE", quantized.palette_rgb.astype(np.uint8).tobytes()))

    # tRNS may stop after the last non-opaque entry; the rest default to opaque.
    alpha = quantized.palette_alpha
    non_opaque = np.flatnonzero(alpha < 255)
    if non_opaque.size:
        parts.append(png_chunk(b"tRNS", alpha[: int(non_opaque[-1]) + 1].tobytes()))

    animated = len(frames) > 1
    if animated:
        parts.append(png_chunk(b"acTL", struct.pack(">II", len(frames), max(loop_count, 0))))

    def delay(i: int) -> bytes:
        return write_delay(delays[i] if delays else default_delay)

    seq = 0
    if animated:
        # dispose_op=0 (leave as-is), blend_op=0 (overwrite): with full-frame or
        # diff-rect SOURCE writes, each frame is exactly what we computed.
        parts.append(png_chunk(b"fcTL", struct.pack(">IIIII", seq, w, h, 0, 0) + delay(0)
                            + bytes([0, 0])))
        seq += 1

    parts.append(png_chunk(b"IDAT", _compress(_scanlines(frames[0], depth))))

    for i in range(1, len(frames)):
        x, y, fw, fh = _changed_rect(frames[i - 1], frames[i])
        sub = frames[i][y:y + fh, x:x + fw]
        parts.append(png_chunk(b"fcTL", struct.pack(">IIIII", seq, fw, fh, x, y) + delay(i)
                            + bytes([0, 0])))
        seq += 1
        parts.append(png_chunk(b"fdAT", struct.pack(">I", seq) + _compress(_scanlines(sub, depth))))
        seq += 1

    parts.append(png_chunk(b"IEND", b""))
    return b"".join(parts)


# ---------------------------------------------------------------------------
# APNG decoding
# ---------------------------------------------------------------------------
#
# We decode APNG ourselves rather than using cv2.imdecodeanimation, which
# mis-composites frames that combine blend_op=OVER with dispose_op=BACKGROUND:
# it corrupts exactly the regions the dispose should have cleared, producing
# colour garbage from a few frames in. Its *still* PNG decoding is correct and
# fast, though, so each frame's own pixels are recovered by rebuilding it as a
# standalone PNG and handing that to imdecode -- only the frame-to-frame
# compositing, which is where the bug lives, is done here.


DISPOSE_NONE, DISPOSE_BACKGROUND, DISPOSE_PREVIOUS = 0, 1, 2
BLEND_SOURCE, BLEND_OVER = 0, 1


class ApngDecodeError(ValueError):
    """Raised when a byte stream is not a decodable APNG."""


@dataclass(frozen=True, slots=True)
class DecodedApng:
    frames_bgra: List[np.ndarray]  # full-canvas BGRA, compositing applied
    delays: List[Fraction]         # exact seconds per frame, as authored
    loop_count: int                # 0 == forever


@dataclass(slots=True)
class _RawFrame:
    x: int
    y: int
    width: int
    height: int
    delay: Fraction
    dispose_op: int
    blend_op: int
    data: List[bytes]


def is_apng(data: bytes) -> bool:
    """True if *data* is a PNG carrying an ``acTL`` chunk (i.e. animated)."""
    return data[:8] == PNG_SIGNATURE and b"acTL" in data


def apng_frame_count(data: bytes) -> int | None:
    """Frame count straight from ``acTL``, without decoding any pixels.

    ``None`` when *data* is not an APNG. Lets callers find out how much work a
    file implies before committing to it -- decoding a large APNG costs seconds,
    and this costs a chunk walk.
    """
    if not is_apng(data):
        return None
    pos = 8
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        if data[pos + 4:pos + 8] == b"acTL":
            return int(struct.unpack(">II", data[pos + 8:pos + 16])[0])
        pos += 12 + length
    return None


def _as_bgra(img: np.ndarray) -> np.ndarray:
    """Normalise whatever imdecode returned to 4-channel BGRA."""
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def _composite_over(dst: np.ndarray, src: np.ndarray) -> np.ndarray:
    """Straight-alpha source-over-destination, both BGRA uint8."""
    sa = src[..., 3:4].astype(np.float32) / 255.0
    da = dst[..., 3:4].astype(np.float32) / 255.0
    out_a = sa + da * (1 - sa)
    safe = np.maximum(out_a, 1e-6)
    rgb = (src[..., :3].astype(np.float32) * sa
           + dst[..., :3].astype(np.float32) * da * (1 - sa)) / safe
    out = np.empty_like(dst)
    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(out_a[..., 0] * 255, 0, 255).astype(np.uint8)
    return np.where(out_a > 0, out, np.zeros_like(out))


def decode_apng(data: bytes) -> DecodedApng:
    """Decode an animated PNG into fully composited BGRA frames.

    Raises :class:`ApngDecodeError` if *data* is not an APNG.
    """
    if not is_apng(data):
        raise ApngDecodeError("not an animated PNG (no acTL chunk)")

    ihdr = b""
    plte: bytes | None = None
    trns: bytes | None = None
    loop_count = 0
    frames: List[_RawFrame] = []
    current: _RawFrame | None = None
    seen_idat = False

    pos = 8
    while pos < len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            ihdr = payload
        elif tag == b"PLTE":
            plte = payload
        elif tag == b"tRNS":
            trns = payload
        elif tag == b"acTL":
            loop_count = struct.unpack(">II", payload[:8])[1]
        elif tag == b"fcTL":
            _seq, fw, fh, fx, fy = struct.unpack(">IIIII", payload[:20])
            delay_num, delay_den = struct.unpack(">HH", payload[20:24])
            current = _RawFrame(fx, fy, fw, fh, read_delay(delay_num, delay_den),
                                payload[24], payload[25], [])
            frames.append(current)
        elif tag == b"IDAT":
            # The default image belongs to the animation only when an fcTL
            # precedes it; otherwise it is a still fallback and not a frame.
            seen_idat = True
            if current is not None and not current.data:
                current.data.append(payload)
            elif current is not None and frames and frames[0] is current:
                current.data.append(payload)
        elif tag == b"fdAT":
            if current is not None:
                current.data.append(payload[4:])
        pos += 12 + length
        if tag == b"IEND":
            break

    if not ihdr or not frames or not seen_idat:
        raise ApngDecodeError("APNG is missing IHDR, IDAT or frame control data")
    frames = [f for f in frames if f.data]
    if not frames:
        raise ApngDecodeError("APNG has no frame data")

    canvas_w, canvas_h = struct.unpack(">II", ihdr[:8])
    tail = ihdr[8:]  # bit depth, colour type, compression, filter, interlace

    def decode_frame(frame: _RawFrame) -> np.ndarray:
        parts = [
            PNG_SIGNATURE,
            png_chunk(b"IHDR", struct.pack(">II", frame.width, frame.height) + tail),
        ]
        if plte is not None:
            parts.append(png_chunk(b"PLTE", plte))
        if trns is not None:
            parts.append(png_chunk(b"tRNS", trns))
        parts.append(png_chunk(b"IDAT", b"".join(frame.data)))
        parts.append(png_chunk(b"IEND", b""))
        img = cv2.imdecode(np.frombuffer(b"".join(parts), dtype=np.uint8),
                           cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ApngDecodeError("a frame's image data could not be decoded")
        return _as_bgra(img)

    canvas = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    out_frames: List[np.ndarray] = []
    for frame in frames:
        sub = decode_frame(frame)
        y0, y1 = frame.y, frame.y + frame.height
        x0, x1 = frame.x, frame.x + frame.width
        if y1 > canvas_h or x1 > canvas_w:
            raise ApngDecodeError("a frame rectangle falls outside the canvas")

        saved = canvas[y0:y1, x0:x1].copy() if frame.dispose_op == DISPOSE_PREVIOUS else None
        if frame.blend_op == BLEND_OVER:
            canvas[y0:y1, x0:x1] = _composite_over(canvas[y0:y1, x0:x1], sub)
        else:
            canvas[y0:y1, x0:x1] = sub
        out_frames.append(canvas.copy())

        # Disposal prepares the canvas for the *next* frame.
        if frame.dispose_op == DISPOSE_BACKGROUND:
            canvas[y0:y1, x0:x1] = 0
        elif saved is not None:
            canvas[y0:y1, x0:x1] = saved

    return DecodedApng(out_frames, [f.delay for f in frames], loop_count)


def encode_palettized_png(
    frames_bgra: Sequence[np.ndarray],
    delays: Sequence[Fraction] = (),
    *,
    loop_count: int = 0,
    max_colors: int = 256,
) -> Tuple[bytes, Quantized]:
    """Quantize then encode in one step; returns the bytes and the palette used.

    The :class:`Quantized` comes back so callers can report palette size and
    whether the reduction was lossless.
    """
    quantized = quantize_bgra(frames_bgra, max_colors=max_colors)
    return encode_apng(quantized, delays, loop_count=loop_count), quantized
