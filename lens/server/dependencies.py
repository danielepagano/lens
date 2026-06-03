from __future__ import annotations

from fastapi import HTTPException, Request

from lens.core.project import ProjectSession
from lens.server.streaming import StreamLock
from lens.server.tts_chunk_coordinator import TtsChunkCoordinator


def get_session(project_slug: str, request: Request) -> ProjectSession:
    projects: dict[str, ProjectSession] = request.app.state.projects
    if project_slug not in projects:
        raise HTTPException(404, detail=f"Project '{project_slug}' not found")
    return projects[project_slug]


def get_stream_lock(project_slug: str, request: Request) -> StreamLock:
    locks: dict[str, StreamLock] = request.app.state.stream_locks
    if project_slug not in locks:
        locks[project_slug] = StreamLock()
    return locks[project_slug]


def get_tts_coordinator(request: Request) -> TtsChunkCoordinator:
    return request.app.state.tts_coordinator
