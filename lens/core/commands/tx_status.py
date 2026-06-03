from __future__ import annotations

from dataclasses import dataclass

from lens.core.exceptions import LensException
from lens.core.project import ProjectSession


@dataclass
class TxStatus:
    pending_files: list[str]
    staged_files: list[str]
    has_remote: bool
    has_upstream: bool
    fetch_error: str | None
    incoming: list[dict[str, str]]
    unpushed: list[dict[str, str]]
    remote_head: dict[str, str] | None


def get_tx_status(session: ProjectSession) -> TxStatus:
    storage = session.new_storage(owner=None)

    pending_files = storage.pending_files() if storage.has_pending() else []
    staged_files = storage.staged_files() if storage.has_staged() else []

    has_remote = storage.has_remote()
    has_upstream = False
    fetch_error: str | None = None
    incoming: list[dict[str, str]] = []
    unpushed: list[dict[str, str]] = []
    remote_head: dict[str, str] | None = None

    if has_remote:
        try:
            storage.fetch_quiet()
            has_upstream = storage.has_upstream()
            if has_upstream:
                incoming = storage.commit_log("HEAD..@{upstream}")
                unpushed = storage.commit_log("@{upstream}..HEAD")
                remote_log = storage.commit_log("@{upstream}", max_count=1)
                remote_head = remote_log[0] if remote_log else None
        except LensException as e:
            fetch_error = str(e)

    return TxStatus(
        pending_files=pending_files,
        staged_files=staged_files,
        has_remote=has_remote,
        has_upstream=has_upstream,
        fetch_error=fetch_error,
        incoming=incoming,
        unpushed=unpushed,
        remote_head=remote_head,
    )
