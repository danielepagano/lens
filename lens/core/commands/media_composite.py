"""Core implementation of ``media composite chromakey``.

Removes a chroma-keyed background from a mount image, either:

- as a preview: runs the algorithm and returns PNG bytes + the resolved
  key/tolerance stats without touching the mount (used by the web UI's
  preview-tweak-save loop). Stills only -- animations are refused, see
  :func:`chromakey_preview`, or
- saved: writes the result back to the mount and tags its sidecar
  ``composite: foreground`` (see issue #99 / ``lens.core.media.metadata``).
  Re-running on the same output path overwrites it, since the CLI's flow is
  to look at the saved file and retune ``--core-tol`` until the cut is clean.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from lens.core.commands.attach import IMAGE_EXTS
from lens.core.exceptions import LensException
from lens.core.media.apng import encode_palettized_png
from lens.core.media.chromakey import (
    CalibrationError,
    DecodeError,
    decode_animation,
    decode_image,
    encode_png,
    parse_hex_key,
    probe_frame_count,
    remove_background,
    remove_background_animation,
)
from lens.core.media import MediaService
from lens.core.mount import MountBackend
from lens.core.project import ProjectSession, get_mount_backend


@dataclass(frozen=True, slots=True)
class _KeyStats:
    """Shared stats from either the still or the animated keying path."""

    key_bgr: tuple[float, float, float]
    core_tol: float
    residual_thresh: float
    dilate_px: int
    n_corners_used: int
    n_frames: int
    palette_colors: int | None   # None when the output is truecolor (still path)


@dataclass(frozen=True, slots=True)
class ChromakeyPreview:
    """Outcome of a ``media composite chromakey`` preview (no mount write)."""

    png_bytes: bytes
    key_hex: str | None          # "#RRGGBB" background color used (detected or given)
    core_tol: float | None
    residual_thresh: float | None
    dilate_px: int | None
    n_corners_used: int | None   # 0 if key was supplied manually (no calibration ran)
    n_frames: int = 1            # > 1 when the source is animated
    palette_colors: int | None = None
    # True when the source is animated and no keying was run: every stat above
    # is None and there are no bytes, because resolving them means doing the
    # whole job. Not an error -- save is still the next step.
    preview_skipped: bool = False


@dataclass(frozen=True, slots=True)
class ChromakeyResult:
    """Outcome of a single ``media composite chromakey`` save call."""

    output_path: str            # mount-relative path of the saved foreground
    key_hex: str
    core_tol: float
    residual_thresh: float
    dilate_px: int
    n_corners_used: int
    n_frames: int = 1
    palette_colors: int | None = None


def _default_output_path(relative_path: str) -> str:
    """``chars/amy.png`` -> ``chars/amy_fg.png``."""
    p = Path(relative_path)
    name = f"{p.stem}_fg.png"
    parent = str(p.parent)
    return f"{parent}/{name}" if parent and parent != "." else name


def _key_hex(key_bgr: tuple[float, float, float]) -> str:
    b, g, r = (int(round(x)) for x in key_bgr)
    return f"#{r:02X}{g:02X}{b:02X}"


def _read_source(session: ProjectSession, relative_path: str) -> tuple[MountBackend, bytes]:
    """Gate on a configured mount and a supported extension, then read the bytes."""
    backend = get_mount_backend(session.project_root)
    if backend is None:
        raise LensException("no mount_point configured in lens.toml")

    ext = Path(relative_path).suffix.lower()
    if ext not in IMAGE_EXTS:
        raise LensException(
            f"unsupported extension '{ext}' for chromakey -- supported: "
            + ", ".join(sorted(IMAGE_EXTS))
        )

    stream = backend.stream_file(relative_path)
    if stream is None:
        raise LensException(f"file not found in mount: {relative_path}")
    return backend, b"".join(stream[0])


def _probe_source_frames(session: ProjectSession, relative_path: str) -> int:
    """Frame count of a mount file without decoding it -- cheap enough to gate on."""
    _backend, source_bytes = _read_source(session, relative_path)
    return probe_frame_count(source_bytes)


def _run_chromakey(
    session: ProjectSession,
    relative_path: str,
    *,
    key: str | None,
    core_tol: float | None,
    residual_thresh: float,
    dilate_px: int | None,
) -> tuple[MountBackend, bytes, _KeyStats]:
    """Shared preview/save path: gate on mount, read+decode+key. No writes.

    Animated sources (GIF, APNG, animated WebP) are keyed frame by frame and
    re-encoded as a palettized animated PNG; stills keep the truecolor PNG
    path. Both are ``.png``, so the destination rules are the same either way.
    """
    backend, source_bytes = _read_source(session, relative_path)

    key_bgr = None
    if key is not None:
        try:
            key_bgr = parse_hex_key(key)
        except ValueError as e:
            raise LensException(str(e)) from e

    # Probe for animation first; a single-frame result falls through to the
    # unchanged still path, so non-animated formats behave exactly as before.
    try:
        decoded = decode_animation(source_bytes)
    except DecodeError:
        decoded = None

    try:
        if decoded is not None and decoded.is_animated:
            animation = remove_background_animation(
                decoded.frames_bgr,
                decoded.delays,
                loop_count=decoded.loop_count,
                core_tol=core_tol,
                residual_thresh=residual_thresh,
                dilate_px=dilate_px,
                key_bgr=key_bgr,
            )
            png_bytes, quantized = encode_palettized_png(
                animation.frames_bgra,
                animation.delays,
                loop_count=animation.loop_count,
            )
            stats = _KeyStats(
                key_bgr=animation.key_bgr,
                core_tol=animation.core_tol,
                residual_thresh=animation.residual_thresh,
                dilate_px=animation.dilate_px,
                n_corners_used=animation.n_corners_used,
                n_frames=len(animation.frames_bgra),
                palette_colors=quantized.n_colors,
            )
            return backend, png_bytes, stats

        img = decode_image(source_bytes)
        result = remove_background(
            img,
            core_tol=core_tol,
            residual_thresh=residual_thresh,
            dilate_px=dilate_px,
            key_bgr=key_bgr,
        )
    except (DecodeError, CalibrationError) as e:
        raise LensException(str(e)) from e

    png_bytes = encode_png(result.bgra)
    stats = _KeyStats(
        key_bgr=result.key_bgr,
        core_tol=result.core_tol,
        residual_thresh=result.residual_thresh,
        dilate_px=result.dilate_px,
        n_corners_used=result.n_corners_used,
        n_frames=1,
        palette_colors=None,
    )
    return backend, png_bytes, stats


def chromakey_preview(
    session: ProjectSession,
    relative_path: str,
    *,
    key: str | None = None,
    core_tol: float | None = None,
    residual_thresh: float = 10.0,
    dilate_px: int | None = None,
) -> ChromakeyPreview:
    """Run chroma-key background removal without writing anything to the mount.

    Animated sources come back with ``preview_skipped`` set instead of a
    rendered preview. Keying an animation is a tens-of-seconds job over every
    frame, and previewing then saving would do the whole thing twice for a
    result that has to travel to the client as a multi-megabyte base64 blob.
    Save writes it straight to the mount instead; retuning means re-running
    save, which is the CLI's flow anyway.

    This is reported as a normal outcome rather than an error so callers can
    tell "nothing to preview" apart from "the request failed" without matching
    on message text, and offer save as the next step either way.

    Raises :class:`LensException` for configuration, validation, or keying
    errors.
    """
    n_frames = _probe_source_frames(session, relative_path)
    if n_frames > 1:
        return ChromakeyPreview(
            png_bytes=b"",
            key_hex=None,
            core_tol=None,
            residual_thresh=None,
            dilate_px=None,
            n_corners_used=None,
            n_frames=n_frames,
            preview_skipped=True,
        )

    _backend, png_bytes, result = _run_chromakey(
        session,
        relative_path,
        key=key,
        core_tol=core_tol,
        residual_thresh=residual_thresh,
        dilate_px=dilate_px,
    )
    return ChromakeyPreview(
        png_bytes=png_bytes,
        key_hex=_key_hex(result.key_bgr),
        core_tol=result.core_tol,
        residual_thresh=result.residual_thresh,
        dilate_px=result.dilate_px,
        n_corners_used=result.n_corners_used,
        n_frames=result.n_frames,
        palette_colors=result.palette_colors,
    )


def chromakey(
    session: ProjectSession,
    relative_path: str,
    *,
    key: str | None = None,
    core_tol: float | None = None,
    residual_thresh: float = 10.0,
    dilate_px: int | None = None,
    out_path: str | None = None,
    media: MediaService | None = None,
) -> ChromakeyResult:
    """Run chroma-key background removal on a mount image and save the result.

    Saves to *out_path* (default: ``<input-stem>_fg.png`` next to
    *relative_path*), tagged ``composite: foreground``. If the destination
    already exists it is overwritten -- this is the tune-and-rerun path for
    ``--core-tol`` and friends.

    *media* is the caller's ``MediaService`` (the server passes its
    per-request instance so the write invalidates the same shared cache
    ``/mount/browse`` reads from); when omitted (CLI, tests) the one
    per-project instance is looked up via ``session.media``.

    Raises :class:`LensException` for configuration, validation, or keying
    errors.
    """
    _backend, png_bytes, result = _run_chromakey(
        session,
        relative_path,
        key=key,
        core_tol=core_tol,
        residual_thresh=residual_thresh,
        dilate_px=dilate_px,
    )
    if media is None:
        media = session.media
        if media is None:
            raise LensException("no mount_point configured in lens.toml")

    dest = out_path or _default_output_path(relative_path)
    if Path(dest).suffix.lower() != ".png":
        raise LensException(f"--out must be a .png path (got {dest!r}) -- chromakey output has alpha")

    dir_path = str(Path(dest).parent) if str(Path(dest).parent) != "." else ""
    filename = Path(dest).name
    try:
        saved_path = media.put_file(dir_path, filename, io.BytesIO(png_bytes))
    except FileExistsError:
        # Overwrite: this is the retune-and-rerun path, not an accidental clash.
        media.delete(dest.lstrip("/"))
        saved_path = media.put_file(dir_path, filename, io.BytesIO(png_bytes))

    media.update_metadata(saved_path, {"composite": "foreground"})

    return ChromakeyResult(
        output_path=saved_path,
        key_hex=_key_hex(result.key_bgr),
        core_tol=result.core_tol,
        residual_thresh=result.residual_thresh,
        dilate_px=result.dilate_px,
        n_corners_used=result.n_corners_used,
        n_frames=result.n_frames,
        palette_colors=result.palette_colors,
    )
