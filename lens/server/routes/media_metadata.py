"""Server routes for media metadata (sidecar) read and write."""

from __future__ import annotations

from typing import Any, Never

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lens.core.media import MediaService
from lens.server.dependencies import get_media_service

router = APIRouter(prefix="/{project_slug}/mount")


class UpdateMetadataRequest(BaseModel):
    metadata: dict[str, Any]


@router.get("/metadata/{path:path}")
def get_metadata(
    path: str,
    media: MediaService | None = Depends(get_media_service),
) -> dict[str, Any]:
    """Return full metadata (path-based + sidecar) for a mount-relative file.

    Response is a flat dict: ``relative_path``, ``name``, ``extension``,
    ``type`` plus any keys from the sidecar YAML.
    """
    if media is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    try:
        meta = media.get_metadata(path)
    except Exception as e:
        _raise_meta_error(e)
    return meta.flattened()


@router.put("/metadata/{path:path}")
def put_metadata(
    path: str,
    body: UpdateMetadataRequest,
    media: MediaService | None = Depends(get_media_service),
) -> dict[str, Any]:
    """Update (merge) sidecar metadata for a mount-relative file.

    The request body's ``metadata`` dict is merged into the sidecar YAML.
    Reserved keys (``relative_path``, ``name``, ``extension``, ``type``) are
    silently ignored if present in the updates.
    """
    if media is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    try:
        meta = media.update_metadata(path, body.metadata)
    except Exception as e:
        _raise_meta_error(e)
    return meta.flattened()


@router.delete("/metadata/{path:path}")
def delete_metadata(
    path: str,
    media: MediaService | None = Depends(get_media_service),
) -> dict[str, Any]:
    """Delete the sidecar metadata file for a mount-relative file.

    The media file itself is not affected — only ``{path}.yml`` is removed.
    Returns a status dict.
    """
    if media is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    try:
        media.delete_metadata(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file not found")
    except Exception as e:
        _raise_meta_error(e)
    return {"status": "ok", "path": path}


def _raise_meta_error(exc: Exception) -> Never:
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail="path escapes the mount directory")
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail="file not found")
    raise HTTPException(status_code=502, detail=f"mount storage error: {exc}")
