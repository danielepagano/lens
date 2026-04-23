"""Server routes for mount-point file browsing, proxying, and attach-at-line."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lens.core.commands.attach import attach as attach_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, get_mount_backend
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")

_PREVIEW_HTML = Path(__file__).parent.parent / "static" / "preview.html"


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
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes the mount directory")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"mount storage error: {e}")
    if entries is None:
        return []
    return entries


@router.get("/mount/file/{path:path}")
def proxy_mount_file(
    path: str,
    session: ProjectSession = Depends(get_session),
) -> StreamingResponse:
    """Proxy a mount-relative file, serving it with the appropriate MIME type."""
    try:
        backend = get_mount_backend(session.project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mount backend error: {e}")
    if backend is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    try:
        result = backend.stream_file(path)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes the mount directory")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"mount storage error: {e}")
    if result is None:
        raise HTTPException(status_code=404, detail=f"file not found: {path}")
    stream, content_type = result
    return StreamingResponse(stream, media_type=content_type)


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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"mount storage error: {e}")
    return {"status": "ok", "path": rel_path}


@router.delete("/mount/file/{path:path}")
def delete_mount_file(
    path: str,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Delete a mount-relative file or empty directory."""
    try:
        backend = get_mount_backend(session.project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mount backend error: {e}")
    if backend is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    try:
        backend.delete(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"not found: {path}")
    except OSError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"mount storage error: {e}")
    return {"status": "ok", "path": path}


class MoveMountRequest(BaseModel):
    to: str


@router.patch("/mount/file/{path:path}")
def move_mount_file(
    path: str,
    body: MoveMountRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Move/rename a mount-relative file."""
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"mount storage error: {e}")
    return {"status": "ok", "path": new_path}


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
