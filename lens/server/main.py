from __future__ import annotations

from fastapi import FastAPI

from lens.core.project import ProjectSession
from lens.server.routes.health import router as health_router


def create_app(session: ProjectSession) -> FastAPI:
    app = FastAPI(title="Lens API")
    app.state.session = session
    app.include_router(health_router)
    return app
