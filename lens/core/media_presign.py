"""Time-limited presigned URLs for mount files (S3-compatible storage only).

Use these when an external HTTPS client (image API, LLM multimodal endpoint,
etc.) must fetch bytes directly from object storage. Do not use for long-lived
links in narrative markdown — URLs expire and are opaque capabilities.

Requires ``mount_point = "s3://..."`` in ``lens.toml``. Local filesystem mounts
cannot be presigned.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from lens.core.exceptions import LensException
from lens.core.mount import S3MountBackend, normalize_subpath
from lens.core.project import get_mount_backend

DEFAULT_MEDIA_PRESIGN_TTL_SECONDS = 60


def presign_mount_read_url(
    project_root: Path,
    mount_subpath: str,
    *,
    expires_in: int = DEFAULT_MEDIA_PRESIGN_TTL_SECONDS,
) -> str:
    """Return a presigned ``GET`` URL for a mount-relative object key.

    Raises :class:`LensException` if the mount is missing, local, or *subpath*
    does not reference an existing file.
    """
    backend = get_mount_backend(project_root)
    if backend is None:
        raise LensException(
            "presigned media URLs require mount_point in lens.toml with s3:// "
            "(reference images need object storage)"
        )
    if not isinstance(backend, S3MountBackend):
        raise LensException(
            "presigned media URLs require an s3:// mount_point "
            "(local filesystem mounts cannot expose URLs to external APIs)"
        )
    sub = normalize_subpath(mount_subpath.strip())
    if not sub:
        raise LensException("mount path for presign is empty")
    if not backend.file_exists(sub):
        raise LensException(f"mount file not found: {sub}")
    return backend.presign_get_object(sub, expires_in=expires_in)


def presign_mount_read_urls(
    project_root: Path,
    mount_subpaths: Sequence[str],
    *,
    expires_in: int = DEFAULT_MEDIA_PRESIGN_TTL_SECONDS,
) -> tuple[str, ...]:
    """Presign each path, preserving order. Skips empty strings after strip."""
    out: list[str] = []
    for raw in mount_subpaths:
        t = str(raw).strip()
        if t:
            out.append(presign_mount_read_url(project_root, t, expires_in=expires_in))
    return tuple(out)
