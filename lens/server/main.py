from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lens.core.project import ProjectSession
from lens.server.routes.narratives import router as narratives_router
from lens.server.routes.node import router as node_router
from lens.server.routes.status import router as status_router
from lens.server.routes.transaction import router as transaction_router
from lens.server.routes.tree import router as tree_router

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(session: ProjectSession) -> FastAPI:
    app = FastAPI(title="Lens API")
    app.state.session = session
    app.include_router(status_router)
    app.include_router(tree_router)
    app.include_router(node_router)
    app.include_router(narratives_router)
    app.include_router(transaction_router)

    # Serve built frontend if present
    if _STATIC_DIR.exists():
        index = _STATIC_DIR / "index.html"
        assets = _STATIC_DIR / "assets"

        if index.exists():
            app.add_api_route("/", lambda: FileResponse(index), response_class=FileResponse)

        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

    return app


def _create_app_from_cwd() -> FastAPI:
    from lens.core.project import require_lens_context

    git_root, project_root = require_lens_context(Path.cwd())
    return create_app(ProjectSession(git_root, project_root))


class _LazyApp:
    _instance: FastAPI | None = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if _LazyApp._instance is None:
            _LazyApp._instance = _create_app_from_cwd()
        await _LazyApp._instance(scope, receive, send)


app = _LazyApp()
