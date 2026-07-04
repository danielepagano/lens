"""Server routes for the release system.

Provides ``POST /{slug}/release/request``, ``GET /{slug}/release/latest``,
and the shared ``ReleaseInfo`` Pydantic model used by transaction and stats
routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lens.core.commands.release import execute_release_clear, execute_release_request
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession
from lens.core.release.version import installed_version, parse_semver_tag
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")


class ReleaseInfo(BaseModel):
    """Release fields embedded in transaction, stats, and release responses."""

    enabled: bool = False
    lens_repo_url: str = ""
    requested_version: str = ""
    requested_from_commit: str = ""
    app_leader: bool = False
    dataset_repos: list[dict[str, str]] = []
    installed_version: str | None = None
    latest_available: str | None = None


class ReleaseRequest(BaseModel):
    target_version: str


@router.post("/release/request")
def release_request(
    body: ReleaseRequest,
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        target = body.target_version.strip()

        sanity = parse_semver_tag(target)
        if sanity is None:
            return {
                "status": "error",
                "detail": f"target_version {target!r} is not a valid vMAJOR.MINOR.PATCH tag",
            }

        inst = installed_version()
        if inst is not None:
            installed = parse_semver_tag(inst)
            if installed is not None and sanity < installed:
                return {
                    "status": "error",
                    "detail": (
                        f"target_version {target} is older than installed "
                        f"version {inst}; cannot request a downgrade"
                    ),
                }

        result = execute_release_request(session.project_root, target)
        return {
            "status": "ok",
            "requested_version": result.requested_version,
            "requested_from_commit": result.requested_from_commit,
        }
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}


@router.post("/release/clear")
def release_clear(
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = execute_release_clear(session.project_root)
        return {"status": "ok", "detail": result.summary}
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}


@router.get("/release/latest")
def release_latest(
    session: ProjectSession = Depends(get_session),
) -> dict[str, Any]:
    from lens.core.release.status import compute_latest_available

    try:
        latest = compute_latest_available(session.project_root)
        return {"latest_available": latest}
    except Exception as e:
        return {"latest_available": None, "error": str(e)}
