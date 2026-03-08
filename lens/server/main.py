from __future__ import annotations

from fastapi import FastAPI

from lens.core.project import ProjectSession
from lens.server.routes.node import router as node_router
from lens.server.routes.status import router as status_router
from lens.server.routes.tree import router as tree_router


def create_app(session: ProjectSession) -> FastAPI:
    app = FastAPI(title="Lens API")
    app.state.session = session
    app.include_router(status_router)
    app.include_router(tree_router)
    app.include_router(node_router)
    return app
