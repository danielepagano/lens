from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from lens.core.commands.check import run_project_check

router = APIRouter()


@router.get("/health")
def global_health(request: Request) -> dict[str, Any]:
    """Server health: runs per-project checks and aggregates results."""
    projects: dict[str, Any] = request.app.state.projects
    project_status: dict[str, str] = {}
    overall_ok = True
    for slug, session in projects.items():
        result = run_project_check(session.project_root)
        errors = [line for line in result.lines if line.severity == "error"]
        if errors:
            project_status[slug] = "; ".join(f"{e.topic}: {e.detail}" for e in errors)
            overall_ok = False
        else:
            project_status[slug] = "ok"
    return {"status": "ok" if overall_ok else "degraded", "projects": project_status}


@router.get("/projects")
def list_projects(request: Request) -> list[dict[str, str]]:
    return [{"slug": slug} for slug in request.app.state.projects]
