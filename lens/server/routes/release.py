"""Server routes for the release system (Phase 5).

All routes resolve to the release leader's ``lens.toml`` when the deployment
serves multiple projects (decision #8) — the slug in the URL is accepted on
input but the leader's state is what gets read and mutated.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from lens.core.commands.release import (
    execute_release_gated_approve,
    execute_release_gated_reject,
    execute_release_policy_update,
)
from lens.core.exceptions import LensException
from lens.core.project import ProjectSession
from lens.core.release.config import find_release_leader_slug
from lens.core.release.status import compute_release_status
from lens.server.dependencies import get_session

router = APIRouter(prefix="/{project_slug}")


class PolicyUpdateRequest(BaseModel):
    auto_update: str | None = None
    requested_version: str | None = None


def _release_session(
    request: Request,
    session: ProjectSession = Depends(get_session),
) -> ProjectSession:
    """Resolve to the release leader's session in a multi-project deploy.

    For single-project deployments the requested slug's session is returned
    directly (the sole project is trivially the leader).  Multi-project
    deployments scan every served project for ``app_leader = true`` and
    return that project's session instead — so all release endpoints
    transparently share a single source of truth regardless of which
    project slug was in the URL.
    """
    projects: dict[str, ProjectSession] = request.app.state.projects
    project_roots: dict[str, Any] = {
        slug: s.project_root for slug, s in projects.items()
    }
    leader_slug = find_release_leader_slug(project_roots)
    if leader_slug is not None:
        return projects[leader_slug]
    return session


@router.get("/release/status")
def release_status(
    project_slug: str,  # noqa: ARG001
    session: ProjectSession = Depends(_release_session),
) -> dict[str, Any]:
    try:
        status = compute_release_status(session.project_root)
    except (RuntimeError, LensException) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not status.enabled:
        raise HTTPException(
            status_code=404,
            detail="release system is not enabled for this project",
        )

    return {
        "enabled": status.enabled,
        "lens_repo_url": status.lens_repo_url,
        "auto_update": status.auto_update,
        "requested_version": status.requested_version,
        "gated_update_pending": status.gated_update_pending,
        "gated_update_target_version": status.gated_update_target_version,
        "gated_update_approved": status.gated_update_approved,
        "app_leader": status.app_leader,
        "installed_version": status.installed_version_str,
        "latest_available": status.latest_available_str,
        "local_checkout_version": status.local_checkout_version,
        "remote_error": status.remote_error,
        "dataset_repos": [
            {
                "name": r.name,
                "git_url": r.git_url,
                "ref": r.ref,
            }
            for r in status.dataset_repos
        ],
    }


@router.post("/release/policy")
def release_policy(
    project_slug: str,  # noqa: ARG001
    body: PolicyUpdateRequest,
    session: ProjectSession = Depends(_release_session),
) -> dict[str, Any]:
    status = compute_release_status(session.project_root)
    if not status.enabled:
        raise HTTPException(
            status_code=404,
            detail="release system is not enabled for this project",
        )

    try:
        execute_release_policy_update(
            session,
            auto_update=body.auto_update,
            requested_version=body.requested_version,
        )
        return {"status": "ok"}
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}


@router.post("/release/gated-update/approve")
def release_gated_approve(
    project_slug: str,  # noqa: ARG001
    session: ProjectSession = Depends(_release_session),
) -> dict[str, Any]:
    status = compute_release_status(session.project_root)
    if not status.enabled:
        raise HTTPException(
            status_code=404,
            detail="release system is not enabled for this project",
        )

    try:
        execute_release_gated_approve(session)
        return {"status": "ok"}
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}


@router.post("/release/gated-update/reject")
def release_gated_reject(
    project_slug: str,  # noqa: ARG001
    session: ProjectSession = Depends(_release_session),
) -> dict[str, Any]:
    status = compute_release_status(session.project_root)
    if not status.enabled:
        raise HTTPException(
            status_code=404,
            detail="release system is not enabled for this project",
        )

    try:
        execute_release_gated_reject(session)
        return {"status": "ok"}
    except (RuntimeError, LensException) as e:
        return {"status": "error", "detail": str(e)}
