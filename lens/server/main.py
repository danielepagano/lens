from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lens.core.project import ProjectSession
from lens.server import routes as routes_pkg
from lens.server.streaming import StreamLock

_STATIC_DIR = Path(__file__).parent / "static"


def _configure_lens_server_logging() -> None:
    """Attach a handler for ``lens.*`` when running under uvicorn.

    Uvicorn configures handlers only for its own loggers; the root logger stays
    without handlers. ``lens`` log records then hit logging's lastResort, which
    only prints WARNING and above — so LLM INFO lines (e.g. HTTP POST start)
    vanish while ERROR (e.g. timeouts) still appear. A dedicated ``lens``
    handler fixes that for ``lens dev`` / ``lens serve`` and reload workers,
    which never run ``lens.cli.main``'s ``basicConfig``.
    """
    lens_log = logging.getLogger("lens")
    if lens_log.handlers:
        return
    lens_log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    lens_log.addHandler(handler)
    lens_log.propagate = False


_configure_lens_server_logging()


def create_app(session: ProjectSession) -> FastAPI:
    app = FastAPI(title="Lens API")
    app.state.session = session
    app.state.stream_lock = StreamLock()
    for _importer, modname, _ispkg in sorted(
        pkgutil.iter_modules(routes_pkg.__path__), key=lambda m: m[1]
    ):
        mod = importlib.import_module(f"{routes_pkg.__name__}.{modname}")
        if hasattr(mod, "router"):
            app.include_router(mod.router)

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
