from __future__ import annotations

from lens.core.project import ProjectSession


def execute_commit(session: ProjectSession) -> None:
    storage = session.new_storage()
    storage.stage_all()
