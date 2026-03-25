from __future__ import annotations

from lens.core.project import ProjectSession


def execute_refresh(session: ProjectSession, *, reset: bool = False) -> None:
    storage = session.new_storage()
    if reset:
        storage.refresh_reset_hard_to_upstream()
    else:
        storage.refresh_fast_forward()
    session.kb.evict_tag_cache()
