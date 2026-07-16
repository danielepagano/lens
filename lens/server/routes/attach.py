"""Server routes for mount-point file browsing, proxying, and attach-at-line."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Never

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lens.core.commands.attach import (
    attach as attach_core,
    get_mount_ref_line_numbers,
    remove_media_references,
    update_media_references,
)
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, get_mount_backend
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")

_PREVIEW_HTML = Path(__file__).parent.parent / "static" / "preview.html"


def _raise_mount_storage_error(exc: Exception) -> Never:
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail="path escapes the mount directory")
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=f"mount path is not readable: {exc}")
    raise HTTPException(status_code=502, detail=f"mount storage error: {exc}")


@router.get("/mount/preview/{path:path}")
def preview_mount_file(project_slug: str, path: str) -> StreamingResponse:  # noqa: ARG001
    """Serve the markdown preview SPA for a mount-relative file."""
    if not _PREVIEW_HTML.exists():
        raise HTTPException(status_code=503, detail="preview app not built — run `lens dev` or `lens serve`")
    content = _PREVIEW_HTML.read_bytes()
    return StreamingResponse(iter([content]), media_type="text/html")


@router.get("/mount/browse")
def browse_mount(
    path: str = "",
    session: ProjectSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List entries in a mount-relative directory.

    Returns [{name, is_dir}] sorted: dirs first, then files.
    Returns [] if mount is not configured or path points to a file.
    """
    try:
        backend = get_mount_backend(session.project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mount backend error: {e}")
    if backend is None:
        return []
    try:
        entries = backend.list_dir(path)
    except Exception as e:
        _raise_mount_storage_error(e)
    if entries is None:
        return []
    return entries


@router.get("/mount/file/{path:path}")
def proxy_mount_file(
    path: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    """Proxy a mount-relative file, serving it with the appropriate MIME type.

    Mobile Safari often requires byte-range (``Range: bytes=...``) support for MP4 playback.
    We support range requests for:
    - Local mount backend (via Starlette's FileResponse which handles Range).
    - S3 mount backend (via ``Range`` on GetObject).
    """
    try:
        backend = get_mount_backend(session.project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mount backend error: {e}")
    if backend is None:
        raise HTTPException(status_code=404, detail="no mount configured")

    try:
        info = backend.get_file_info(path)
    except Exception as e:
        _raise_mount_storage_error(e)
    if info is None:
        raise HTTPException(status_code=404, detail=f"file not found: {path}")
    total, content_type = info

    range_hdr = request.headers.get("range")
    if not range_hdr:
        try:
            stream = backend.stream_file_range(path, start=None, end=None)
        except Exception as e:
            _raise_mount_storage_error(e)
        if stream is None:
            raise HTTPException(status_code=404, detail=f"file not found: {path}")
        headers: dict[str, str] = {"Accept-Ranges": "bytes"}
        if total:
            headers["Content-Length"] = str(total)
        return StreamingResponse(stream, media_type=content_type, headers=headers)

    # Parse a single HTTP byte range: "bytes=start-end"
    if not range_hdr.startswith("bytes="):
        raise HTTPException(status_code=416, detail="invalid range")
    spec = range_hdr[len("bytes=") :].strip()
    if "," in spec:
        raise HTTPException(status_code=416, detail="multiple ranges not supported")
    start_s, end_s = (spec.split("-", 1) + [""])[:2]
    if start_s == "" and end_s == "":
        raise HTTPException(status_code=416, detail="invalid range")

    try:
        if start_s == "":
            suffix = int(end_s)
            if suffix <= 0:
                raise HTTPException(status_code=416, detail="invalid range")
            start = max(total - suffix, 0)
            end = total - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s != "" else total - 1
    except ValueError:
        raise HTTPException(status_code=416, detail="invalid range")

    if total <= 0 or start < 0 or start >= total or end < start:
        raise HTTPException(status_code=416, detail="range out of bounds")
    end = min(end, total - 1)
    length = end - start + 1

    try:
        stream = backend.stream_file_range(path, start=start, end=end)
    except Exception as e:
        _raise_mount_storage_error(e)
    if stream is None:
        raise HTTPException(status_code=404, detail=f"file not found: {path}")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{total}",
        "Content-Length": str(length),
    }
    return StreamingResponse(stream, media_type=content_type, status_code=206, headers=headers)


@router.post("/mount/upload")
async def upload_mount_file(
    dir: str = Form(...),
    file: UploadFile = File(...),
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Upload a file to a mount-relative directory, creating it if needed."""
    try:
        backend = get_mount_backend(session.project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mount backend error: {e}")
    if backend is None:
        raise HTTPException(status_code=400, detail="no mount configured")
    filename = Path(file.filename or "upload").name
    try:
        rel_path = backend.put_file(dir, filename, file.file)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        _raise_mount_storage_error(e)
    return {"status": "ok", "path": rel_path}


@router.delete("/mount/file/{path:path}")
def delete_mount_file(
    path: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Delete a mount-relative file or empty directory.

    When references exist in narrative/knowledge files and ``confirmed`` is not
    ``true``, returns a 409-like response listing the references.  The client
    may then re-send with ``?confirmed=true`` to perform the actual deletion
    plus reference cleanup.
    """
    try:
        backend = get_mount_backend(session.project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mount backend error: {e}")
    if backend is None:
        raise HTTPException(status_code=404, detail="no mount configured")

    confirmed = request.query_params.get("confirmed", "false").lower() == "true"

    refs = get_mount_ref_line_numbers(session.project_root, path)
    if refs and not confirmed:
        ref_list = [
            {"file": file_path, "line_numbers": line_numbers}
            for file_path, line_numbers in sorted(refs.items())
        ]
        return {"status": "confirm_required", "path": path, "refs": ref_list}

    refs_cleaned = 0
    if refs:
        refs_cleaned = remove_media_references(session.project_root, path)

    try:
        backend.delete(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"not found: {path}")
    except PermissionError as e:
        _raise_mount_storage_error(e)
    except OSError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        _raise_mount_storage_error(e)
    return {"status": "ok", "path": path, "refs_cleaned": refs_cleaned}


class MoveMountRequest(BaseModel):
    to: str


@router.patch("/mount/file/{path:path}")
def move_mount_file(
    path: str,
    body: MoveMountRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Move/rename a mount-relative file and update embed references in narrative/knowledge."""
    try:
        backend = get_mount_backend(session.project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mount backend error: {e}")
    if backend is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    try:
        new_path = backend.move(path, body.to)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"not found: {path}")
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        _raise_mount_storage_error(e)
    refs_updated = update_media_references(session.project_root, path, body.to)
    return {"status": "ok", "path": new_path, "refs_updated": refs_updated}


class AttachRequest(BaseModel):
    path: str
    address: str | None = None
    line: int | None = None


@router.post("/attach")
def attach(
    body: AttachRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Attach a mount-relative media file after a line in a narrative node."""
    try:
        result = attach_core(session, body.path, address=body.address, line=body.line)
        return {"status": "ok", "type": result["type"], "embed": result["embed"]}
    except LensException as e:
        return {"status": "error", "detail": str(e)}
