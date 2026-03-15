"""Server routes for mount-point file browsing, proxying, and attach-at-cursor."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from lens.core.commands.attach import SUPPORTED_EXTENSIONS, attach as attach_core
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession, get_mount_point
from lens.server.dependencies import get_session

router = APIRouter()

_PREVIEW_HTML = Path(__file__).parent.parent / "static" / "preview.html"


def _resolve_mount_path(mount: Path, relative: str) -> Path:
    """Resolve a mount-relative path and validate it stays within mount root."""
    full = (mount / relative.lstrip("/")).resolve()
    try:
        full.relative_to(mount)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes the mount directory")
    return full


@router.get("/mount/preview/{path:path}")
def preview_mount_file(path: str) -> FileResponse:  # noqa: ARG001
    """Serve the markdown preview SPA for a mount-relative file."""
    if not _PREVIEW_HTML.exists():
        raise HTTPException(status_code=503, detail="preview app not built — run `lens dev` or `lens serve`")
    return FileResponse(str(_PREVIEW_HTML), media_type="text/html")


@router.get("/mount/browse")
def browse_mount(
    path: str = "",
    session: ProjectSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List entries in a mount-relative directory.

    Returns [{name, is_dir}] sorted: dirs first, then files.
    Returns [] if mount is not configured or path points to a file.
    """
    mount = get_mount_point(session.project_root)
    if mount is None:
        return []
    target = _resolve_mount_path(mount, path)
    if not target.exists() or not target.is_dir():
        return []

    def _include(p: Path) -> bool:
        if p.name.startswith("."):
            return False
        if p.is_dir():
            return True
        return p.suffix.lower() in SUPPORTED_EXTENSIONS

    entries = sorted(
        (p for p in target.iterdir() if _include(p)),
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )
    return [{"name": e.name, "is_dir": e.is_dir()} for e in entries]


@router.get("/mount/file/{path:path}")
def proxy_mount_file(
    path: str,
    session: ProjectSession = Depends(get_session),
) -> FileResponse:
    """Proxy a mount-relative file, serving it with the appropriate MIME type."""
    mount = get_mount_point(session.project_root)
    if mount is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    full = _resolve_mount_path(mount, path)
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {path}")
    return FileResponse(str(full))


@router.post("/mount/upload")
async def upload_mount_file(
    dir: str = Form(...),
    file: UploadFile = File(...),
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Upload a file to a mount-relative directory, creating it if needed."""
    mount = get_mount_point(session.project_root)
    if mount is None:
        raise HTTPException(status_code=400, detail="no mount configured")
    target_dir = _resolve_mount_path(mount, dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "upload").name
    dest = target_dir / filename
    if dest.exists():
        raise HTTPException(
            status_code=409,
            detail=f"file already exists: {dir.rstrip('/')}/{filename}",
        )
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "ok", "path": str(dest.relative_to(mount))}


@router.delete("/mount/file/{path:path}")
def delete_mount_file(
    path: str,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Delete a mount-relative file or empty directory."""
    mount = get_mount_point(session.project_root)
    if mount is None:
        raise HTTPException(status_code=404, detail="no mount configured")
    full = _resolve_mount_path(mount, path)
    if not full.exists():
        raise HTTPException(status_code=404, detail=f"not found: {path}")
    if full.is_dir():
        try:
            full.rmdir()
        except OSError:
            raise HTTPException(status_code=409, detail="directory is not empty")
    else:
        full.unlink()
    return {"status": "ok", "path": path}


class AttachRequest(BaseModel):
    path: str


@router.post("/attach")
def attach(
    body: AttachRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Attach a mount-relative media file at the narrative cursor."""
    try:
        result = attach_core(session, body.path)
        return {"status": "ok", "type": result["type"], "embed": result["embed"]}
    except LensException as e:
        return {"status": "error", "detail": str(e)}
