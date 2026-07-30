"""Server routes for the media-composite chromakey preview/save UI flow."""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lens.core.commands.media_composite import chromakey as chromakey_core
from lens.core.commands.media_composite import chromakey_preview
from lens.core.exceptions import LensException
from lens.core.media import MediaService
from lens.core.project import ProjectSession
from lens.server.dependencies import get_media_service, get_session

router = APIRouter(prefix="/{project_slug}/mount")


class ChromakeyRequestBody(BaseModel):
    path: str
    key: str | None = None
    core_tol: float | None = None
    residual_thresh: float = 10.0
    dilate_px: int | None = None


class ChromakeySaveRequestBody(ChromakeyRequestBody):
    out_path: str | None = None


@router.post("/composite/chromakey/preview")
def preview_chromakey(
    project_slug: str,
    body: ChromakeyRequestBody,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    """Run chroma-key background removal and return PNG bytes as base64.

    Nothing is written to the mount -- this is the "preview, tweak tolerance,
    repeat" step before the client explicitly calls ``/composite/chromakey/save``.
    """
    _ = project_slug
    try:
        result = chromakey_preview(
            session,
            body.path,
            key=body.key,
            core_tol=body.core_tol,
            residual_thresh=body.residual_thresh,
            dilate_px=body.dilate_px,
        )
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "png_b64": base64.b64encode(result.png_bytes).decode("ascii"),
        "key_hex": result.key_hex,
        "core_tol": result.core_tol,
        "residual_thresh": result.residual_thresh,
        "dilate_px": result.dilate_px,
        "n_corners_used": result.n_corners_used,
    }


@router.post("/composite/chromakey/save")
def save_chromakey(
    project_slug: str,
    body: ChromakeySaveRequestBody,
    session: ProjectSession = Depends(get_session),
    media: MediaService | None = Depends(get_media_service),
) -> dict[str, Any]:
    """Re-run chroma-key background removal and save the result to the mount.

    Tags the saved file's sidecar ``composite: foreground``. Re-running with
    the same (default or ``out_path``) destination overwrites it.
    """
    _ = project_slug
    try:
        result = chromakey_core(
            session,
            body.path,
            key=body.key,
            core_tol=body.core_tol,
            residual_thresh=body.residual_thresh,
            dilate_px=body.dilate_px,
            out_path=body.out_path,
            media=media,
        )
    except LensException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "output_path": result.output_path,
        "key_hex": result.key_hex,
        "core_tol": result.core_tol,
        "residual_thresh": result.residual_thresh,
        "dilate_px": result.dilate_px,
        "n_corners_used": result.n_corners_used,
    }
