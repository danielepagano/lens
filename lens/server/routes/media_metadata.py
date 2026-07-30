"""Server routes for media metadata (sidecar) read and write."""

from __future__ import annotations

from typing import Any, Never

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from lens.core.exceptions import MediaSearchCapacityExceeded
from lens.core.media import MediaService, SearchPage
from lens.server.dependencies import get_media_service

router = APIRouter(prefix="/{project_slug}/mount")


@router.get("/search")
def search_media(
    q: str = Query(..., description="Search query string"),
    page: int = Query(1, ge=1, description="Page number (1-indexed, 20 results per page)"),
    media: MediaService | None = Depends(get_media_service),
) -> dict[str, Any]:
    """Search media files by keyword, KV, and nested KV filters.

    Query syntax (space-separated tokens):
    - ``word!``        — required term (must appear somewhere)
    - ``key:value``    — top-level KV pair match
    - ``path/sub:val`` — nested KV pair match
    - ``word``         — optional keyword (scores hits, at least one needed)

    Example: ``amy! house! type:image composite/type:subject couch bed``
    """
    if media is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    try:
        result: SearchPage = media.search(q, page=page)
    except MediaSearchCapacityExceeded as e:
        raise HTTPException(status_code=507, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"search error: {e}")
    items: list[dict[str, Any]] = []
    for r in result.items:
        try:
            meta = media.get_metadata(r.relative_path)
        except Exception:
            continue
        entry = meta.flattened()
        entry["_score"] = r.score
        items.append(entry)
    return {
        "items": items,
        "total_items": result.total_items,
        "total_pages": result.total_pages,
        "page_size": result.page_size,
        "current_page": result.current_page,
    }


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
