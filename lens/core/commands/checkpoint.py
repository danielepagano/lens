from __future__ import annotations

from datetime import datetime, timezone

from lens.core.project import ProjectSession


def default_checkpoint_message() -> str:
    return f"lens checkpoint {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"


def execute_checkpoint(
    session: ProjectSession,
    message: str | None = None,
    push: bool = True,
) -> None:
    storage = session.new_storage()
    msg = message or default_checkpoint_message()
    storage.checkpoint(msg)
    if push and storage.has_remote():
        storage.push()
