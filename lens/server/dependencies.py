from __future__ import annotations

from fastapi import Request

from lens.core.project import ProjectSession


def get_session(request: Request) -> ProjectSession:
    return request.app.state.session  # type: ignore[no-any-return]
