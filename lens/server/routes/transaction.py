from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lens.core.commands.checkpoint import execute_checkpoint
from lens.core.commands.commit import execute_commit
from lens.core.commands.refresh import execute_refresh
from lens.core.commands.rollback import rollback
from lens.core.commands.tx_status import get_tx_status
from lens.core.project import ProjectSession
from lens.core.exceptions import LensException
from lens.server.dependencies import get_session

from .release import ReleaseInfo

router = APIRouter(prefix="/{project_slug}")


class CheckpointRequest(BaseModel):
    message: str | None = None
    push: bool | None = None


class RefreshRequest(BaseModel):
    reset: bool | None = None


class RollbackResponse(BaseModel):
    status: str
    detail: str | None = None
    owner: str | None = None
    is_mutation: bool | None = None


class CommitResponse(BaseModel):
    status: str
    detail: str | None = None


class CheckpointResponse(BaseModel):
    status: str
    detail: str | None = None
    release: ReleaseInfo | None = None


class RefreshEntry(BaseModel):
    name: str
    status: str
    action: str
    detail: str


class RefreshResultResponse(BaseModel):
    status: str
    detail: str | None = None
    entries: list[RefreshEntry] = []
    any_changed: bool = False
    release: ReleaseInfo | None = None


class TxStatusCommit(BaseModel):
    hash: str
    message: str


class TxStatusResponse(BaseModel):
    pending_files: list[str] = []
    staged_files: list[str] = []
    has_remote: bool = False
    has_upstream: bool = False
    fetch_error: str | None = None
    incoming: list[TxStatusCommit] = []
    unpushed: list[TxStatusCommit] = []
    remote_head: TxStatusCommit | None = None
    release: ReleaseInfo | None = None


def _release_info(session: ProjectSession) -> ReleaseInfo | None:
    """Build ``ReleaseInfo`` for embedding in transaction responses."""
    import tomllib

    from lens.core.release.config import (
        parse_dataset_repo_configs,
        parse_release_config,
    )
    from lens.core.release.status import compute_release_status
    from lens.core.release.version import installed_version

    lens_toml = session.project_root / "lens.toml"
    if not lens_toml.exists():
        return None

    with lens_toml.open("rb") as f:
        raw: dict[str, Any] = tomllib.load(f)

    cfg = parse_release_config(raw)
    if not cfg.enabled:
        return None

    dataset_repos = parse_dataset_repo_configs(raw)
    rls_status = compute_release_status(session.project_root)

    return ReleaseInfo(
        enabled=True,
        lens_repo_url=cfg.lens_repo_url,
        requested_version=cfg.requested_version,
        requested_from_commit=cfg.requested_from_commit,
        app_leader=cfg.app_leader,
        dataset_repos=[
            {"name": r.name, "git_url": r.git_url, "ref": r.ref}
            for r in dataset_repos
        ],
        installed_version=installed_version(),
        latest_available=rls_status.latest_available_str,
        update_available=rls_status.update_available,
    )


@router.post("/rollback", response_model=RollbackResponse)
def rollback_route(session: ProjectSession = Depends(get_session)) -> RollbackResponse:
    try:
        result = rollback(session)
        if not result.performed:
            return RollbackResponse(
                status="ok",
                detail="no pending transaction",
            )
        s = result.status
        return RollbackResponse(
            status="ok",
            detail="transaction rolled back",
            owner=str(s.owner) if s.owner is not None else None,
            is_mutation=s.is_mutation,
        )
    except (RuntimeError, LensException) as e:
        return RollbackResponse(status="error", detail=str(e))


@router.post("/commit", response_model=CommitResponse)
def commit(session: ProjectSession = Depends(get_session)) -> CommitResponse:
    try:
        execute_commit(session)
        return CommitResponse(status="ok")
    except (RuntimeError, LensException) as e:
        return CommitResponse(status="error", detail=str(e))


@router.post("/checkpoint", response_model=CheckpointResponse)
def checkpoint(
    body: CheckpointRequest | None,
    session: ProjectSession = Depends(get_session),
) -> CheckpointResponse:
    try:
        message = body.message if body is not None else None
        push = body.push if body is not None and body.push is not None else True
        execute_checkpoint(session, message=message, push=push)
        return CheckpointResponse(status="ok", release=_release_info(session))
    except (RuntimeError, LensException) as e:
        return CheckpointResponse(status="error", detail=str(e))


@router.post("/refresh", response_model=RefreshResultResponse)
def refresh(
    body: RefreshRequest | None,
    session: ProjectSession = Depends(get_session),
) -> RefreshResultResponse:
    try:
        reset = body.reset if body is not None and body.reset is not None else False
        result = execute_refresh(session, reset=reset)
        return RefreshResultResponse(
            status="ok",
            entries=[
                RefreshEntry(
                    name=e.name,
                    status=e.status,
                    action=e.action,
                    detail=e.detail,
                )
                for e in result.entries
            ],
            any_changed=result.any_changed,
            release=_release_info(session),
        )
    except (RuntimeError, LensException) as e:
        return RefreshResultResponse(status="error", detail=str(e))


@router.get("/tx/status", response_model=TxStatusResponse)
def tx_status(session: ProjectSession = Depends(get_session)) -> TxStatusResponse:
    result = get_tx_status(session)
    incoming = [
        TxStatusCommit(
            hash=c.get("hash", ""),
            message=c.get("message", ""),
        )
        for c in result.incoming
    ]
    unpushed = [
        TxStatusCommit(
            hash=c.get("hash", ""),
            message=c.get("message", ""),
        )
        for c in result.unpushed
    ]
    remote_head = (
        TxStatusCommit(
            hash=result.remote_head.get("hash", ""),
            message=result.remote_head.get("message", ""),
        )
        if result.remote_head is not None
        else None
    )
    return TxStatusResponse(
        pending_files=result.pending_files,
        staged_files=result.staged_files,
        has_remote=result.has_remote,
        has_upstream=result.has_upstream,
        fetch_error=result.fetch_error,
        incoming=incoming,
        unpushed=unpushed,
        remote_head=remote_head,
        release=_release_info(session),
    )
