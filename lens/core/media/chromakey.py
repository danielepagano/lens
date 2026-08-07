"""Chroma-key background removal for illustrations (bordered characters, not photos).

Pure pixel logic — no mount/file I/O. Ported from a reference implementation
(see issue #102) that models edge pixels as an alpha-blend between a near-black
ink outline and the flat background color, rather than a fixed-radius feather.
That's what makes it hold up on thin detail (hairline strands, ribbons) that a
spatial feather would erode.
"""

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from lens.core.media.apng import (
    ApngDecodeError,
    apng_frame_count,
    decode_apng,
    encode_palettized_png,
    is_apng,
)
from fractions import Fraction


@dataclass
class KeyResult:
    bgra: np.ndarray                     # keyed image, BGRA, straight alpha
    key_bgr: Tuple[float, float, float]  # background color used (detected or given)
    core_tol: float
    residual_thresh: float
    dilate_px: int
    n_corners_used: int                  # 0 if key_bgr was supplied manually (no calibration ran)


class CalibrationError(ValueError):
    """Raised when no background color could be auto-detected and none was supplied."""


class DecodeError(ValueError):
    """Raised when input bytes could not be decoded as an image."""


# ---------------------------------------------------------------------------
# Calibration: flood-fill sampling to auto-detect background color and a safe
# core tolerance. Not used for final masking (blind to enclosed background
# regions -- see _key_math), only for characterizing the color.
# ---------------------------------------------------------------------------


def corner_looks_like_background(
    patch_bgr: np.ndarray, min_brightness: float = 40, max_internal_std: float = 20
) -> bool:
    """No hue assumption: any flat, non-black solid-color patch qualifies.

    The keying math doesn't require magenta specifically, only that the
    background is distinguishable from character content and from black
    (edge pixels are modeled as blending toward black ink outlines).
    """
    flat = patch_bgr.reshape(-1, 3).std(axis=0).mean() < max_internal_std
    bright_enough = patch_bgr.reshape(-1, 3).mean() > min_brightness
    return bool(flat and bright_enough)


@dataclass(frozen=True, slots=True)
class Calibration:
    key_bgr: Tuple[float, float, float]
    core_tol: float
    n_corners_used: int


def calibrate(
    img_bgr: np.ndarray, patch: int = 40, sample_tol: float = 45, smooth: int = 0
) -> Optional[Calibration]:
    """Border-seeded flood-fill sampling of background color and its natural variance.

    Used to derive a data-driven ``core_tol`` instead of a fixed guess.
    ``sample_tol=45`` is a safety-first choice: raising it to reach noisier
    near-edge background was found to leak into real skin-tone content on
    some inputs. If a generator's output has unusually noisy edges, override
    ``core_tol`` on that image rather than loosening this default.

    ``smooth`` (odd kernel size, 0 to disable) median-blurs a *guide* copy used
    only for the corner check and the flood fill. Palettized sources dither
    their flat areas, and dithering defeats both: the corner fails the flatness
    test, and fixed-range fill cannot span a channel whose spread exceeds
    ``sample_tol``. Statistics are still measured on the untouched pixels, so
    the color estimate gets the benefit of denoising while ``core_tol`` still
    reflects the real noise the keyer has to clear.

    Returns ``None`` if no corner looks like a plausible flat background —
    caller must supply ``key_bgr`` explicitly in that case.
    """
    if smooth and (smooth < 3 or smooth % 2 == 0):
        raise ValueError(f"smooth must be 0 or an odd value >= 3 (got {smooth})")
    guide = cv2.medianBlur(img_bgr, smooth) if smooth else img_bgr

    h, w = img_bgr.shape[:2]
    corners = [(0, 0), (w - patch, 0), (0, h - patch), (w - patch, h - patch)]
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    diff = (sample_tol,) * 3
    n_used = 0

    for cx, cy in corners:
        patch_img = guide[cy:cy + patch, cx:cx + patch]
        if not corner_looks_like_background(patch_img):
            continue
        seed = (cx + patch // 2, cy + patch // 2)
        cv2.floodFill(guide.copy(), mask, seed,
                       tuple(int(x) for x in guide[seed[1], seed[0]]), diff, diff, flags)
        n_used += 1

    sample_mask = mask[1:-1, 1:-1] > 0
    pixels = img_bgr[sample_mask].astype(np.float32)
    if len(pixels) < 500:
        return None

    key = np.median(pixels, axis=0)
    dist = np.linalg.norm(pixels - key, axis=1)
    core_tol = float(np.clip(np.percentile(dist, 99.5) * 1.3, 15, 200))
    b, g, r = (float(x) for x in key)
    return Calibration(key_bgr=(b, g, r), core_tol=core_tol, n_corners_used=n_used)


# ---------------------------------------------------------------------------
# Core keying math
# ---------------------------------------------------------------------------


def _key_math(
    img_bgr: np.ndarray,
    key_bgr: Tuple[float, float, float],
    core_tol: float,
    residual_thresh: float,
    dilate_px: int,
) -> np.ndarray:
    """Two-tier model.

    Tier 1 (core): plain distance test, clears confident interior background
    anywhere in the image (not border-flood-fill-based, so enclosed
    background pockets are handled too).

    Tier 2 (zone, a dilation ring around core): edge pixels are modeled as
    alpha-blends between a near-black ink outline and the background --
    ``P = alpha*black + (1-alpha)*B``, so ``P`` is a scalar multiple of
    ``B``. Alpha is recoverable by projection rather than a spatial feather
    radius. Pixels that don't fit this model (real content -- skin, blush,
    colored cloth) are despilled but kept opaque.
    """
    P = img_bgr.astype(np.float64)
    B = np.array(key_bgr, dtype=np.float64)

    core_dist = np.linalg.norm(P - B, axis=2)
    core_bg = core_dist < core_tol

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1,) * 2)
    zone = cv2.dilate(core_bg.astype(np.uint8), kernel).astype(bool) & ~core_bg

    dot_PB = (P * B).sum(axis=2)
    dot_BB = (B * B).sum()
    t = dot_PB / dot_BB
    proj = t[..., None] * B
    residual = np.linalg.norm(P - proj, axis=2)
    fit_good = residual < residual_thresh
    alpha_line = np.clip(1 - t, 0, 1)

    alpha = np.ones(img_bgr.shape[:2], dtype=np.float64)
    alpha[core_bg] = 0.0
    alpha[zone & fit_good] = alpha_line[zone & fit_good]
    alpha_u8 = (alpha * 255).astype(np.uint8)

    is_blend = (zone & fit_good) & (alpha > 0.02) & (alpha < 0.98)
    out = P.copy()
    out[is_blend] = 0
    out[core_bg] = 0

    needs_despill = zone & ~fit_good
    b, g, r = out[..., 0], out[..., 1], out[..., 2]
    kb, kg, kr = B
    if kr > kg and kb > kg:  # magenta-family key (elevated R and B, low G)
        spill = np.clip(np.minimum(r, b) - g, 0, None)
        out[..., 0] = np.where(needs_despill, np.clip(b - spill, 0, 255), out[..., 0])
        out[..., 2] = np.where(needs_despill, np.clip(r - spill, 0, 255), out[..., 2])
    # Other key hue families would need their own despill direction; magenta
    # is the only one validated so far.

    out_u8 = out.astype(np.uint8)
    return cv2.merge([*cv2.split(out_u8), alpha_u8])


def remove_background(
    img_bgr: np.ndarray,
    *,
    core_tol: Optional[float] = None,
    residual_thresh: float = 10.0,
    dilate_px: Optional[int] = None,
    key_bgr: Optional[Tuple[float, float, float]] = None,
) -> KeyResult:
    """Remove a chroma-key background from an already-decoded BGR array.

    ``core_tol`` is the one parameter worth overriding by hand for an
    unusually noisy input; the rest have defaults that hold up across tested
    cases but remain real overrides.

    Raises :class:`CalibrationError` if ``key_bgr`` is not given and no
    corner looks like a plausible background.
    """
    if dilate_px is None:
        dilate_px = max(20, img_bgr.shape[1] // 60)  # scales with resolution

    n_corners = 0
    resolved_core_tol: float
    if key_bgr is None:
        calib = calibrate(img_bgr)
        if calib is None:
            raise CalibrationError(
                "no corner looks like a flat background -- pass key_bgr explicitly"
            )
        key_bgr = calib.key_bgr
        n_corners = calib.n_corners_used
        resolved_core_tol = core_tol if core_tol is not None else calib.core_tol
    else:
        resolved_core_tol = core_tol if core_tol is not None else 40.0  # no calibration to derive from

    bgra = _key_math(img_bgr, key_bgr, resolved_core_tol, residual_thresh, dilate_px)
    return KeyResult(bgra, key_bgr, resolved_core_tol, residual_thresh, dilate_px, n_corners)


# ---------------------------------------------------------------------------
# Bytes-in/bytes-out convenience for mount-backed callers
# ---------------------------------------------------------------------------


def decode_image(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise DecodeError("couldn't decode image bytes")
    return img


def encode_png(bgra: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", bgra)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


def remove_background_bytes(
    image_bytes: bytes,
    *,
    core_tol: Optional[float] = None,
    residual_thresh: float = 10.0,
    dilate_px: Optional[int] = None,
    key_bgr: Optional[Tuple[float, float, float]] = None,
) -> bytes:
    """Image bytes in, PNG bytes out. Use :func:`remove_background` directly
    when the calibration/tolerance stats (:class:`KeyResult`) are also needed."""
    img = decode_image(image_bytes)
    result = remove_background(
        img, core_tol=core_tol, residual_thresh=residual_thresh,
        dilate_px=dilate_px, key_bgr=key_bgr,
    )
    return encode_png(result.bgra)


# ---------------------------------------------------------------------------
# Animated input (GIF / APNG / animated WebP) -> palettized APNG
# ---------------------------------------------------------------------------


# Median kernel for the calibration guide image. Sized for dither noise, which
# is a 1px checker pattern; 3 clears it. Harmless on clean truecolor sources
# (APNG, animated WebP) -- a median over a flat region returns that region.
DITHER_SMOOTH = 3


@dataclass(frozen=True, slots=True)
class DecodedAnimation:
    frames_bgr: List[np.ndarray]  # composited (disposal already applied)
    delays: List[Fraction]        # exact seconds per frame, as authored
    loop_count: int               # 0 == forever

    @property
    def is_animated(self) -> bool:
        return len(self.frames_bgr) > 1


@dataclass
class AnimationKeyResult:
    frames_bgra: List[np.ndarray]        # straight alpha, one per source frame
    delays: List[Fraction]               # exact seconds per frame, as authored
    loop_count: int
    key_bgr: Tuple[float, float, float]
    core_tol: float
    residual_thresh: float
    dilate_px: int
    n_corners_used: int
    calibration_frame: int               # frame the key was measured on; -1 if supplied


def probe_frame_count(image_bytes: bytes) -> int:
    """How many frames *image_bytes* holds, without decoding them all.

    APNG answers from ``acTL`` alone; other formats decode at most two frames,
    which is enough to tell a still from an animation. Callers use this to
    decide whether a job is worth starting -- keying a large animation costs
    tens of seconds, so it should never be run speculatively.

    Returns 1 for anything that isn't decodable as an animation.
    """
    count = apng_frame_count(image_bytes)
    if count is not None:
        return count
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    try:
        ok, animation = cv2.imdecodeanimation(arr, 0, 2)
    except cv2.error:
        return 1
    return len(animation.frames) if ok and animation.frames else 1


def decode_animation(image_bytes: bytes) -> DecodedAnimation:
    """Decode any animated (or still) image into composited BGR frames.

    APNG goes through :func:`lens.core.media.apng.decode_apng` rather than
    OpenCV, which mis-composites ``blend_op=OVER`` over ``dispose_op=BACKGROUND``
    and corrupts frames a few into the sequence. GIF and WebP keep the OpenCV
    path, which handles them correctly.

    Frames come back already composited, so disposal methods and partial frame
    rects are resolved here and every frame is a full picture.
    """
    if is_apng(image_bytes):
        try:
            decoded = decode_apng(image_bytes)
        except ApngDecodeError as e:
            raise DecodeError(str(e)) from e
        return DecodedAnimation(
            [f[..., :3].copy() for f in decoded.frames_bgra],
            decoded.delays,
            decoded.loop_count,
        )

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    ok, animation = cv2.imdecodeanimation(arr)
    if not ok or not animation.frames:
        raise DecodeError("couldn't decode image bytes as an animation")
    frames = [f[..., :3] if f.ndim == 3 and f.shape[2] == 4 else f for f in animation.frames]
    # OpenCV only reports whole milliseconds for GIF/WebP, which is all those
    # formats store anyway (GIF delays are centiseconds).
    delays = [Fraction(int(d), 1000) for d in animation.durations]
    return DecodedAnimation(list(frames), delays, int(animation.loop_count))


def remove_background_animation(
    frames_bgr: Sequence[np.ndarray],
    delays: Sequence[Fraction] = (),
    *,
    loop_count: int = 0,
    core_tol: Optional[float] = None,
    residual_thresh: float = 10.0,
    dilate_px: Optional[int] = None,
    key_bgr: Optional[Tuple[float, float, float]] = None,
) -> AnimationKeyResult:
    """Key every frame of an animation against one shared background colour.

    Calibration runs **once**, not per frame. Re-measuring each frame lets
    ``key_bgr`` and ``core_tol`` drift with whatever the encoder's quantizer did
    to that frame, and the cut boundary then shimmers frame to frame — very
    visible in motion even when each frame looks fine alone. The first frame
    that calibrates wins and its numbers are pinned for the whole sequence.

    Raises :class:`CalibrationError` if no frame yields a usable background and
    none was supplied.
    """
    if not frames_bgr:
        raise DecodeError("animation has no frames")

    resolved_core_tol: float
    calibration_frame = -1
    n_corners = 0
    if key_bgr is None:
        for i, frame in enumerate(frames_bgr):
            calib = calibrate(frame, smooth=DITHER_SMOOTH)
            if calib is not None:
                key_bgr = calib.key_bgr
                n_corners = calib.n_corners_used
                resolved_core_tol = core_tol if core_tol is not None else calib.core_tol
                calibration_frame = i
                break
        else:
            raise CalibrationError(
                "no frame has a corner that looks like a flat background "
                "-- pass key_bgr explicitly"
            )
    else:
        resolved_core_tol = core_tol if core_tol is not None else 40.0

    # Pin dilate_px too: it is resolution-derived, and all frames share a size.
    if dilate_px is None:
        dilate_px = max(20, frames_bgr[0].shape[1] // 60)

    keyed = [
        _key_math(frame, key_bgr, resolved_core_tol, residual_thresh, dilate_px)
        for frame in frames_bgr
    ]
    return AnimationKeyResult(
        frames_bgra=keyed,
        delays=list(delays),
        loop_count=loop_count,
        key_bgr=key_bgr,
        core_tol=resolved_core_tol,
        residual_thresh=residual_thresh,
        dilate_px=dilate_px,
        n_corners_used=n_corners,
        calibration_frame=calibration_frame,
    )


def remove_background_animation_bytes(
    image_bytes: bytes,
    *,
    core_tol: Optional[float] = None,
    residual_thresh: float = 10.0,
    dilate_px: Optional[int] = None,
    key_bgr: Optional[Tuple[float, float, float]] = None,
    max_colors: int = 256,
) -> bytes:
    """Animated image bytes in, palettized APNG bytes out.

    Use :func:`decode_animation` + :func:`remove_background_animation` directly
    when the calibration stats or the resulting palette are also needed.
    """
    decoded = decode_animation(image_bytes)
    result = remove_background_animation(
        decoded.frames_bgr,
        decoded.delays,
        loop_count=decoded.loop_count,
        core_tol=core_tol,
        residual_thresh=residual_thresh,
        dilate_px=dilate_px,
        key_bgr=key_bgr,
    )
    png_bytes, _quantized = encode_palettized_png(
        result.frames_bgra,
        result.delays,
        loop_count=result.loop_count,
        max_colors=max_colors,
    )
    return png_bytes


def parse_hex_key(hexcolor: str) -> Tuple[float, float, float]:
    """Parse an ``RRGGBB`` (optional leading ``#``) string into a ``(b, g, r)`` tuple."""
    hexcolor = hexcolor.lstrip("#")
    if len(hexcolor) != 6:
        raise ValueError(f"invalid hex color {hexcolor!r}; expected RRGGBB")
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
    return (float(b), float(g), float(r))
