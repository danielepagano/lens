"""Core implementation of ``media composite chromakey``.

Removes a chroma-keyed background from a mount image, either:

- as a preview: runs the algorithm and returns PNG bytes + the resolved
  key/tolerance stats without touching the mount (used by the web UI's
  preview-tweak-save loop), or
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
from lens.core.media.chromakey import (
    CalibrationError,
    DecodeError,
    KeyResult,
    decode_image,
    encode_png,
    parse_hex_key,
    remove_background,
)
from lens.core.media.metadata import MediaStore
from lens.core.mount import MountBackend
from lens.core.project import ProjectSession, get_mount_backend


@dataclass(frozen=True, slots=True)
class ChromakeyPreview:
    """Outcome of a ``media composite chromakey`` preview (no mount write)."""

    png_bytes: bytes
    key_hex: str                 # "#RRGGBB" background color used (detected or given)
    core_tol: float
    residual_thresh: float
    dilate_px: int
    n_corners_used: int          # 0 if key was supplied manually (no calibration ran)


@dataclass(frozen=True, slots=True)
class ChromakeyResult:
    """Outcome of a single ``media composite chromakey`` save call."""

    output_path: str            # mount-relative path of the saved foreground
    key_hex: str
    core_tol: float
    residual_thresh: float
    dilate_px: int
    n_corners_used: int


def _default_output_path(relative_path: str) -> str:
    """``chars/amy.png`` -> ``chars/amy_fg.png``."""
    p = Path(relative_path)
    name = f"{p.stem}_fg.png"
    parent = str(p.parent)
    return f"{parent}/{name}" if parent and parent != "." else name


def _key_hex(key_bgr: tuple[float, float, float]) -> str:
    b, g, r = (int(round(x)) for x in key_bgr)
    return f"#{r:02X}{g:02X}{b:02X}"


def _run_chromakey(
    session: ProjectSession,
    relative_path: str,
    *,
    key: str | None,
    core_tol: float | None,
    residual_thresh: float,
    dilate_px: int | None,
) -> tuple[MountBackend, bytes, KeyResult]:
    """Shared preview/save path: gate on mount, read+decode+key. No writes."""
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
    source_bytes = b"".join(stream[0])

    key_bgr = None
    if key is not None:
        try:
            key_bgr = parse_hex_key(key)
        except ValueError as e:
            raise LensException(str(e)) from e

    try:
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
    return backend, png_bytes, result


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
    return ChromakeyPreview(
        png_bytes=png_bytes,
        key_hex=_key_hex(result.key_bgr),
        core_tol=result.core_tol,
        residual_thresh=result.residual_thresh,
        dilate_px=result.dilate_px,
        n_corners_used=result.n_corners_used,
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
) -> ChromakeyResult:
    """Run chroma-key background removal on a mount image and save the result.

    Saves to *out_path* (default: ``<input-stem>_fg.png`` next to
    *relative_path*), tagged ``composite: foreground``. If the destination
    already exists it is overwritten -- this is the tune-and-rerun path for
    ``--core-tol`` and friends.

    Raises :class:`LensException` for configuration, validation, or keying
    errors.
    """
    backend, png_bytes, result = _run_chromakey(
        session,
        relative_path,
        key=key,
        core_tol=core_tol,
        residual_thresh=residual_thresh,
        dilate_px=dilate_px,
    )

    dest = out_path or _default_output_path(relative_path)
    if Path(dest).suffix.lower() != ".png":
        raise LensException(f"--out must be a .png path (got {dest!r}) -- chromakey output has alpha")

    dir_path = str(Path(dest).parent) if str(Path(dest).parent) != "." else ""
    filename = Path(dest).name
    try:
        saved_path = backend.put_file(dir_path, filename, io.BytesIO(png_bytes))
    except FileExistsError:
        # Overwrite: this is the retune-and-rerun path, not an accidental clash.
        backend.delete(dest.lstrip("/"))
        saved_path = backend.put_file(dir_path, filename, io.BytesIO(png_bytes))

    MediaStore(backend).update_metadata(saved_path, {"composite": "foreground"})

    return ChromakeyResult(
        output_path=saved_path,
        key_hex=_key_hex(result.key_bgr),
        core_tol=result.core_tol,
        residual_thresh=result.residual_thresh,
        dilate_px=result.dilate_px,
        n_corners_used=result.n_corners_used,
    )
